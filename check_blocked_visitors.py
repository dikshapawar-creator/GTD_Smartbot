#!/usr/bin/env python3
"""
Check if IP or fingerprint is in blocked visitors table
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.models.blocked import BlockedVisitor

def check_blocked():
    db = SessionLocal()
    try:
        # Check for the IP from logs
        test_ip = "103.44.53.14"
        
        blocked_by_ip = db.query(BlockedVisitor).filter(
            BlockedVisitor.ip_address == test_ip
        ).all()
        
        print(f"🔍 Checking IP: {test_ip}")
        if blocked_by_ip:
            print("❌ IP is BLOCKED:")
            for block in blocked_by_ip:
                print(f"   Reason: {block.reason}")
                print(f"   Blocked at: {block.blocked_at}")
        else:
            print("✅ IP is NOT blocked")
            
        # Check all blocked visitors
        all_blocked = db.query(BlockedVisitor).all()
        print(f"\n📋 Total blocked visitors: {len(all_blocked)}")
        for block in all_blocked:
            print(f"   IP: {block.ip_address}, Fingerprint: {block.visitor_fingerprint}, Reason: {block.reason}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    check_blocked()