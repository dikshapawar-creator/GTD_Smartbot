import os
import re

versions_dir = r"c:\Users\Harsh kumar\Desktop\GTT_smartbot\Backend_bot\alembic\versions"
files = [f for f in os.listdir(versions_dir) if f.endswith(".py")]

nodes = {} # rev -> down_rev
rev_to_file = {}

for f in files:
    path = os.path.join(versions_dir, f)
    with open(path, "r") as src:
        content = src.read()
        rev_match = re.search(r"revision[:\s]+str\s*=\s*['\"]([^'\"]+)['\"]", content)
        if not rev_match:
            rev_match = re.search(r"revision\s*=\s*['\"]([^'\"]+)['\"]", content)
        
        down_match = re.search(r"down_revision[:\s\w\[\],]+=\s*['\"]([^'\"]+)['\"]", content)
        if not down_match:
             down_match = re.search(r"down_revision\s*=\s*['\"]([^'\"]+)['\"]", content)
        
        if rev_match:
            rev = rev_match.group(1)
            down = down_match.group(1) if down_match else None
            nodes[rev] = down
            rev_to_file[rev] = f

print("--- Migration Graph ---")
all_revs = set(nodes.keys())
all_downs = set(nodes.values()) - {None}

heads = all_revs - all_downs
bases = [r for r, d in nodes.items() if d is None]

print(f"Nodes found: {len(nodes)}")
for rev, down in nodes.items():
    print(f"  {rev} -> {down} ({rev_to_file[rev]})")

print("\n--- Summary ---")
print(f"HEADS: {heads}")
print(f"BASES: {bases}")

if len(heads) > 1:
    print("\nCONFLICT DETECTED: Multiple heads found.")
