#!/usr/bin/env python3
"""
Claude Context Sync - Simplified version with no external dependencies
"""

import os
import json
import hashlib
import datetime
import argparse
import subprocess
import time
import platform
import getpass
import sys
from pathlib import Path
from typing import Dict

# Windows consoles default to a legacy codepage that can't print the emoji output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class ClaudeSync:
    def __init__(self, config_path: str = "~/.claude-sync/config.json"):
        self.config_path = Path(config_path).expanduser()
        self.config = self.load_config()
        self.sync_dir = Path(self.config.get("sync_dir", "~/.claude-sync/contexts")).expanduser()
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        
    def load_config(self) -> Dict:
        """Load or create configuration"""
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                return json.load(f)
        
        # Create default config
        default_config = {
            "sync_method": "git",
            "git_repo": "",
            "auto_sync": True,
            "machine_id": self.generate_machine_id()
        }
        
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(default_config, f, indent=2)
        
        return default_config
    
    def generate_machine_id(self) -> str:
        """Generate unique machine identifier"""
        # os.uname() and os.getuid() don't exist on Windows
        user = os.getuid() if hasattr(os, "getuid") else getpass.getuser()
        machine_info = f"{platform.node()}-{user}"
        return hashlib.md5(machine_info.encode()).hexdigest()[:8]
    
    def run_git_command(self, args: list, cwd: Path = None) -> tuple:
        """Run a git command and return (success, output)"""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=cwd or self.sync_dir,
                capture_output=True,
                text=True,
                check=True
            )
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            return False, e.stderr
    
    def sync_git(self, operation: str = "both") -> bool:
        """Sync using Git repository"""
        repo_path = self.sync_dir / "repo"
        
        # Clone repository if it doesn't exist
        if not repo_path.exists():
            print(f"Cloning repository...")
            success, output = self.run_git_command(
                ["clone", self.config["git_repo"], str(repo_path)]
            )
            if not success:
                print(f"Failed to clone repository: {output}")
                return False
        
        # Change to repo directory
        original_dir = os.getcwd()
        os.chdir(repo_path)
        
        try:
            if operation in ["pull", "both"]:
                print("Pulling latest changes...")
                success, output = self.run_git_command(["pull", "--rebase"], repo_path)
                
                if success:
                    # Copy contexts to working directory
                    for context_file in repo_path.glob("*.md"):
                        if context_file.name not in ["README.md", "LICENSE.md"]:
                            self.merge_context(context_file)
                else:
                    print(f"Pull failed: {output}")
            
            if operation in ["push", "both"]:
                # Copy local context to repo
                claude_md = Path(original_dir) / "CLAUDE.md"
                if claude_md.exists():
                    dest = repo_path / f"CLAUDE-{self.config['machine_id']}.md"
                    dest.write_text(claude_md.read_text())
                    
                    # Stage, commit and push
                    self.run_git_command(["add", "."], repo_path)
                    
                    commit_msg = f"Update from {self.config['machine_id']} at {datetime.datetime.now()}"
                    self.run_git_command(["commit", "-m", commit_msg], repo_path)
                    
                    print("Pushing changes...")
                    success, output = self.run_git_command(["push"], repo_path)
                    if not success:
                        print(f"Push failed: {output}")
                        return False
                else:
                    print("No CLAUDE.md file found in current directory")
        
        finally:
            os.chdir(original_dir)
        
        return True
    
    def merge_context(self, remote_file: Path) -> None:
        """Merge remote context with local"""
        local_claude = Path.cwd() / "CLAUDE.md"
        
        if not local_claude.exists():
            # No local file, just copy
            local_claude.write_text(remote_file.read_text())
            print(f"Created CLAUDE.md from {remote_file.name}")
            return
        
        # Simple merge: append unique content
        local_content = local_claude.read_text()
        remote_content = remote_file.read_text()
        
        if remote_content not in local_content:
            # Backup local
            backup = local_claude.with_suffix(".md.bak")
            backup.write_text(local_content)
            
            # Merge by appending
            merged = local_content + "\n\n" + f"# Merged from {remote_file.stem}\n\n" + remote_content
            local_claude.write_text(merged)
            print(f"Merged content from {remote_file.name}")
    
    def sync(self, operation: str = "both") -> bool:
        """Main sync method"""
        if not self.config.get("git_repo"):
            print("Error: No Git repository configured. Run 'setup' first.")
            return False
        
        return self.sync_git(operation)
    
    def setup_hooks(self) -> None:
        """Setup Claude Code hooks for automatic sync"""
        hooks_dir = Path.home() / ".claude-code" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        
        script_path = Path(__file__).absolute()
        
        # Create session-start hook
        start_hook = hooks_dir / "session-start.sh"
        start_hook.write_text(f"""#!/bin/bash
# Auto-sync Claude context at session start
cd ~
{script_path} pull
""")
        start_hook.chmod(0o755)
        
        # Create session-end hook  
        end_hook = hooks_dir / "session-end.sh"
        end_hook.write_text(f"""#!/bin/bash
# Auto-sync Claude context at session end
cd ~
{script_path} push
""")
        end_hook.chmod(0o755)
        
        print(f"✅ Hooks installed in {hooks_dir}")
        print("Context will sync automatically on session start/end")


def main():
    parser = argparse.ArgumentParser(description="Claude Context Sync")
    parser.add_argument("action", choices=["setup", "sync", "pull", "push", "hooks"],
                        help="Action to perform")
    parser.add_argument("--git-repo", help="Git repository URL for sync")
    
    args = parser.parse_args()
    
    sync = ClaudeSync()
    
    if args.action == "setup":
        if args.git_repo:
            sync.config["git_repo"] = args.git_repo
            with open(sync.config_path, 'w') as f:
                json.dump(sync.config, f, indent=2)
            print(f"✅ Configuration saved to {sync.config_path}")
            print(f"Repository: {args.git_repo}")
            print(f"Machine ID: {sync.config['machine_id']}")
        else:
            print("Error: --git-repo required for setup")
    
    elif args.action == "sync":
        if sync.sync("both"):
            print("✅ Sync completed")
    
    elif args.action == "pull":
        if sync.sync("pull"):
            print("✅ Pull completed")
    
    elif args.action == "push":
        if sync.sync("push"):
            print("✅ Push completed")
    
    elif args.action == "hooks":
        sync.setup_hooks()


if __name__ == "__main__":
    main()