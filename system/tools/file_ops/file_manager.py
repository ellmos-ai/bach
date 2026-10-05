#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Tool: file_manager
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version file_manager

Description:
    [Beschreibung hinzufügen]

Usage:
    python file_manager.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"


import os
import sys
import argparse
import json
import shutil
import time
from datetime import datetime

def get_file_info(path):
    if not os.path.exists(path):
        return {"error": "File not found", "path": path}
    
    stat = os.stat(path)
    return {
        "path": os.path.abspath(path),
        "size": stat.st_size,
        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "is_file": os.path.isfile(path),
        "is_dir": os.path.isdir(path)
    }

def read_file(path, encoding='utf-8'):
    if not os.path.exists(path):
        return {"error": "File not found", "path": path}
    try:
        with open(path, 'r', encoding=encoding) as f:
            content = f.read()
        return {"path": path, "content": content, "length": len(content)}
    except Exception as e:
        return {"error": str(e), "path": path}

def write_file(path, content, encoding='utf-8', overwrite=False):
    if os.path.exists(path) and not overwrite:
        return {"error": "File exists and overwrite is False", "path": path}
    try:
        # Create directories if they don't exist
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w', encoding=encoding) as f:
            f.write(content)
        return {"success": True, "path": path, "bytes_written": len(content)}
    except Exception as e:
        return {"error": str(e), "path": path}

def append_file(path, content, encoding='utf-8'):
    if not os.path.exists(path):
        return {"error": "File not found", "path": path}
    try:
        with open(path, 'a', encoding=encoding) as f:
            f.write(content)
        return {"success": True, "path": path, "bytes_written": len(content)}
    except Exception as e:
        return {"error": str(e), "path": path}

def delete_file(path):
    if not os.path.exists(path):
        return {"error": "File not found", "path": path}
    try:
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        return {"success": True, "path": path, "operation": "delete"}
    except Exception as e:
        return {"error": str(e), "path": path}

def copy_file(src, dst):
    if not os.path.exists(src):
        return {"error": "Source not found", "path": src}
    try:
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return {"success": True, "src": src, "dst": dst, "operation": "copy"}
    except Exception as e:
        return {"error": str(e)}

def move_file(src, dst):
    if not os.path.exists(src):
        return {"error": "Source not found", "path": src}
    try:
        shutil.move(src, dst)
        return {"success": True, "src": src, "dst": dst, "operation": "move"}
    except Exception as e:
        return {"error": str(e)}

def list_dir(path):
    if not os.path.exists(path):
        return {"error": "Path not found", "path": path}
    if not os.path.isdir(path):
        return {"error": "Not a directory", "path": path}
    try:
        items = []
        for entry in os.scandir(path):
            items.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else 0,
                "modified": datetime.fromtimestamp(entry.stat().st_mtime).isoformat()
            })
        return {"path": path, "items": items, "count": len(items)}
    except Exception as e:
        return {"error": str(e), "path": path}

def main():
    parser = argparse.ArgumentParser(description="BACH File Manager Tool")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Info
    parser_info = subparsers.add_parser("info", help="Get file info")
    parser_info.add_argument("path", help="Path to file")

    # Read
    parser_read = subparsers.add_parser("read", help="Read file content")
    parser_read.add_argument("path", help="Path to file")

    # Write
    parser_write = subparsers.add_parser("write", help="Write content to file")
    parser_write.add_argument("path", help="Path to file")
    parser_write.add_argument("content", help="Content to write")
    parser_write.add_argument("--overwrite", action="store_true", help="Overwrite if exists")

    # Append
    parser_append = subparsers.add_parser("append", help="Append content to file")
    parser_append.add_argument("path", help="Path to file")
    parser_append.add_argument("content", help="Content to append")

    # Delete
    parser_delete = subparsers.add_parser("delete", help="Delete file or directory")
    parser_delete.add_argument("path", help="Path to delete")

    # Copy
    parser_copy = subparsers.add_parser("copy", help="Copy file or directory")
    parser_copy.add_argument("src", help="Source path")
    parser_copy.add_argument("dst", help="Destination path")

    # Move
    parser_move = subparsers.add_parser("move", help="Move file or directory")
    parser_move.add_argument("src", help="Source path")
    parser_move.add_argument("dst", help="Destination path")

    # List
    parser_list = subparsers.add_parser("list", help="List directory contents")
    parser_list.add_argument("path", help="Directory path")

    args = parser.parse_args()

    result = {}

    if args.command == "info":
        result = get_file_info(args.path)
    elif args.command == "read":
        result = read_file(args.path)
    elif args.command == "write":
        result = write_file(args.path, args.content, overwrite=args.overwrite)
    elif args.command == "append":
        result = append_file(args.path, args.content)
    elif args.command == "delete":
        result = delete_file(args.path)
    elif args.command == "copy":
        result = copy_file(args.src, args.dst)
    elif args.command == "move":
        result = move_file(args.src, args.dst)
    elif args.command == "list":
        result = list_dir(args.path)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
