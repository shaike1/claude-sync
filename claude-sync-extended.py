#!/usr/bin/env python3
"""
Claude Context Sync Extended - Sync all Claude Code data between PCs
"""

import os
import json
import shutil
import hashlib
import datetime
import argparse
import subprocess
import platform
import getpass
import sys
from pathlib import Path
from typing import Dict, List

# Windows consoles default to a legacy codepage that can't print the emoji output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class ClaudeSyncExtended:
    def __init__(self, config_path: str = "~/.claude-sync/config.json"):
        self.config_path = Path(config_path).expanduser()
        self.config = self.load_config()
        self.sync_dir = Path(self.config.get("sync_dir", "~/.claude-sync/data")).expanduser()
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        
        # Define what to sync
        self.sync_items = {
            "essential": {
                "claude_config": "~/.claude.json",
                "claude_settings": "~/.claude/settings.local.json", 
                "context_file": "CLAUDE.md",
                "session_data": "~/.claude/projects/",
                "todos": "~/.claude/todos/"
            },
            "optional": {
                "shell_snapshots": "~/.claude/shell-snapshots/",
                "slash_commands": "~/.claude-code/slash-commands/"
            }
        }
    
    def load_config(self) -> Dict:
        """Load or create configuration"""
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                return json.load(f)
        
        default_config = {
            "sync_method": "git",
            "git_repo": "",
            "machine_id": self.generate_machine_id(),
            "sync_level": "essential",  # essential, full
            "exclude_patterns": ["*.log", "*.tmp", "cache/*"]
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
    
    def prepare_sync_data(self) -> Path:
        """Prepare data for sync by copying to staging area"""
        staging_dir = self.sync_dir / "staging" / self.config["machine_id"]
        staging_dir.mkdir(parents=True, exist_ok=True)
        
        # Clear staging
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        
        sync_level = self.config.get("sync_level", "essential")
        items_to_sync = self.sync_items["essential"].copy()
        
        if sync_level == "full":
            items_to_sync.update(self.sync_items["optional"])
        
        # Copy files to staging
        for item_name, item_path in items_to_sync.items():
            source_path = Path(item_path).expanduser()
            dest_path = staging_dir / item_name
            
            try:
                if source_path.is_file():
                    # Copy file
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, dest_path)
                    print(f"✓ Staged {item_name}: {source_path}")
                    
                elif source_path.is_dir():
                    # Copy directory
                    if source_path.exists():
                        shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                        print(f"✓ Staged {item_name}/: {source_path}")
                        
                elif item_name == "context_file":
                    # Handle CLAUDE.md in current directory
                    claude_md = Path.cwd() / "CLAUDE.md"
                    if claude_md.exists():
                        shutil.copy2(claude_md, dest_path)
                        print(f"✓ Staged {item_name}: {claude_md}")
                        
            except Exception as e:
                print(f"⚠ Warning: Could not stage {item_name}: {e}")
        
        # Create metadata
        metadata = {
            "machine_id": self.config["machine_id"],
            "hostname": platform.node(),
            "timestamp": datetime.datetime.now().isoformat(),
            "sync_level": sync_level,
            "synced_items": list(items_to_sync.keys())
        }
        
        with open(staging_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        
        return staging_dir
    
    def restore_sync_data(self, repo_path: Path) -> None:
        """Restore synced data from repository"""
        # Find all machine data
        machine_dirs = [d for d in repo_path.iterdir() if d.is_dir() and d.name != '.git']
        
        for machine_dir in machine_dirs:
            if machine_dir.name == self.config["machine_id"]:
                continue  # Skip our own data
                
            metadata_file = machine_dir / "metadata.json"
            if not metadata_file.exists():
                continue
                
            with open(metadata_file) as f:
                metadata = json.load(f)
            
            print(f"🔄 Restoring data from {metadata['hostname']} ({metadata['timestamp']})")
            
            # Restore each item
            for item_name in metadata.get("synced_items", []):
                source_file = machine_dir / item_name
                
                if not source_file.exists():
                    continue
                
                # Determine restore location
                if item_name in self.sync_items["essential"]:
                    restore_path = Path(self.sync_items["essential"][item_name]).expanduser()
                elif item_name in self.sync_items["optional"]:
                    restore_path = Path(self.sync_items["optional"][item_name]).expanduser()
                else:
                    continue
                
                try:
                    if item_name == "context_file":
                        # Special handling for CLAUDE.md
                        claude_md = Path.cwd() / "CLAUDE.md"
                        self.merge_claude_md(source_file, claude_md)
                        
                    elif item_name == "claude_config":
                        # Merge Claude configuration carefully
                        self.merge_claude_config(source_file, restore_path)
                        
                    elif item_name == "session_data":
                        # Merge session data
                        self.merge_directory(source_file, restore_path, merge_mode="append")
                        
                    elif source_file.is_file():
                        # Simple file copy with backup
                        if restore_path.exists():
                            backup_path = restore_path.with_suffix(f"{restore_path.suffix}.bak")
                            shutil.copy2(restore_path, backup_path)
                        
                        restore_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_file, restore_path)
                        print(f"✓ Restored {item_name}")
                        
                    elif source_file.is_dir():
                        # Directory merge
                        self.merge_directory(source_file, restore_path, merge_mode="update")
                        print(f"✓ Merged {item_name}/")
                        
                except Exception as e:
                    print(f"⚠ Error restoring {item_name}: {e}")
    
    def merge_claude_config(self, source_file: Path, dest_file: Path) -> None:
        """Intelligently merge Claude configuration files"""
        try:
            # Load both configs
            if dest_file.exists():
                with open(dest_file) as f:
                    local_config = json.load(f)
            else:
                local_config = {}
            
            with open(source_file) as f:
                remote_config = json.load(f)
            
            # Merge strategy:
            # - Keep local userID and oauthAccount
            # - Merge projects (MCP servers, etc.)
            # - Update tips and other shared settings
            
            merged_config = local_config.copy()
            
            # Merge projects
            if "projects" in remote_config:
                if "projects" not in merged_config:
                    merged_config["projects"] = {}
                
                for project_path, project_config in remote_config["projects"].items():
                    if project_path not in merged_config["projects"]:
                        merged_config["projects"][project_path] = project_config
                    else:
                        # Merge MCP servers
                        if "mcpServers" in project_config:
                            if "mcpServers" not in merged_config["projects"][project_path]:
                                merged_config["projects"][project_path]["mcpServers"] = {}
                            merged_config["projects"][project_path]["mcpServers"].update(
                                project_config["mcpServers"]
                            )
            
            # Merge other settings (but preserve account info)
            preserve_keys = {"userID", "oauthAccount"}
            for key, value in remote_config.items():
                if key not in preserve_keys and key != "projects":
                    merged_config[key] = value
            
            # Write merged config
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_file, 'w') as f:
                json.dump(merged_config, f, indent=2)
                
        except Exception as e:
            print(f"Warning: Could not merge Claude config: {e}")
    
    def merge_claude_md(self, source_file: Path, dest_file: Path) -> None:
        """Merge CLAUDE.md files intelligently"""
        if not dest_file.exists():
            shutil.copy2(source_file, dest_file)
            return
        
        # Read both files
        with open(source_file) as f:
            remote_content = f.read()
        with open(dest_file) as f:
            local_content = f.read()
        
        # Simple merge - append unique sections
        if remote_content.strip() not in local_content:
            # Create backup
            backup = dest_file.with_suffix(".md.bak")
            shutil.copy2(dest_file, backup)
            
            # Append remote content
            with open(dest_file, 'w') as f:
                f.write(local_content)
                f.write(f"\n\n# Merged from {source_file.parent.name}\n\n")
                f.write(remote_content)
    
    def merge_directory(self, source_dir: Path, dest_dir: Path, merge_mode: str = "update") -> None:
        """Merge directories based on mode"""
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        for item in source_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(source_dir)
                dest_item = dest_dir / rel_path
                
                if merge_mode == "append" or not dest_item.exists():
                    dest_item.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_item)
                elif merge_mode == "update":
                    # Update if source is newer
                    if item.stat().st_mtime > dest_item.stat().st_mtime:
                        shutil.copy2(item, dest_item)
    
    def sync_git(self, operation: str = "both") -> bool:
        """Sync using Git repository"""
        repo_path = self.sync_dir / "repo"
        
        # Clone if needed
        if not repo_path.exists():
            print("🔽 Cloning repository...")
            try:
                subprocess.run([
                    "git", "clone", self.config["git_repo"], str(repo_path)
                ], check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                print(f"❌ Clone failed: {e}")
                return False
        
        original_dir = os.getcwd()
        os.chdir(repo_path)
        
        try:
            if operation in ["pull", "both"]:
                print("📥 Pulling latest changes...")
                subprocess.run(["git", "pull", "--rebase"], check=True, capture_output=True)
                self.restore_sync_data(repo_path)
            
            if operation in ["push", "both"]:
                print("📤 Preparing data for sync...")
                staging_dir = self.prepare_sync_data()
                
                # Copy staging to repo
                machine_dir = repo_path / self.config["machine_id"]
                if machine_dir.exists():
                    shutil.rmtree(machine_dir)
                shutil.copytree(staging_dir, machine_dir)
                
                # Commit and push
                subprocess.run(["git", "add", "."], check=True)
                commit_msg = f"Sync from {self.config['machine_id']} at {datetime.datetime.now()}"
                subprocess.run(["git", "commit", "-m", commit_msg], check=False)
                subprocess.run(["git", "push"], check=True)
                
                print("✅ Data synced to repository")
        
        except subprocess.CalledProcessError as e:
            print(f"❌ Sync failed: {e}")
            return False
        finally:
            os.chdir(original_dir)
        
        return True
    
    def sync(self, operation: str = "both") -> bool:
        """Main sync method"""
        if not self.config.get("git_repo"):
            print("❌ No Git repository configured. Run 'setup' first.")
            return False
        
        return self.sync_git(operation)


def main():
    parser = argparse.ArgumentParser(description="Claude Context Sync Extended")
    parser.add_argument("action", choices=["setup", "sync", "pull", "push", "status"],
                        help="Action to perform")
    parser.add_argument("--git-repo", help="Git repository URL for sync")
    parser.add_argument("--level", choices=["essential", "full"], 
                        default="essential", help="Sync level")
    
    args = parser.parse_args()
    
    sync = ClaudeSyncExtended()
    
    if args.action == "setup":
        if args.git_repo:
            sync.config["git_repo"] = args.git_repo
            sync.config["sync_level"] = args.level
            with open(sync.config_path, 'w') as f:
                json.dump(sync.config, f, indent=2)
            print(f"✅ Configuration saved")
            print(f"Repository: {args.git_repo}")
            print(f"Sync level: {args.level}")
            print(f"Machine ID: {sync.config['machine_id']}")
        else:
            print("❌ --git-repo required for setup")
    
    elif args.action == "status":
        print("📊 Claude Sync Extended Status")
        print("=" * 30)
        print(f"Config: {sync.config_path}")
        print(f"Repository: {sync.config.get('git_repo', 'Not configured')}")
        print(f"Sync level: {sync.config.get('sync_level', 'essential')}")
        print(f"Machine ID: {sync.config['machine_id']}")
        
        # Show what would be synced
        sync_level = sync.config.get("sync_level", "essential")
        items = sync.sync_items["essential"].copy()
        if sync_level == "full":
            items.update(sync.sync_items["optional"])
        
        print(f"\n📁 Items to sync ({sync_level}):")
        for name, path in items.items():
            full_path = Path(path).expanduser()
            exists = "✓" if full_path.exists() else "✗"
            print(f"  {exists} {name}: {path}")
    
    elif args.action in ["sync", "pull", "push"]:
        if sync.sync(args.action):
            print(f"✅ {args.action.title()} completed")


if __name__ == "__main__":
    main()