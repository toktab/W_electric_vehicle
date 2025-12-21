#!/usr/bin/env python3
"""
Auto-Start CPs - Simple version that just recreates containers from scratch
Copies the EXACT logic from ev_cp_manager.py
"""

import json
import os
import subprocess
import time
import sys

REGISTRY_FILE = "data/registry.txt"
NETWORK = "w_electric_vehicle_evcharging_net"

def print_header(text):
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")

def load_registry():
    """Load all CPs from registry.txt"""
    if not os.path.exists(REGISTRY_FILE):
        print(f"⚠️  Registry file not found: {REGISTRY_FILE}")
        return []
    
    cps = []
    try:
        with open(REGISTRY_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    cp_data = json.loads(line)
                    cps.append(cp_data)
    except Exception as e:
        print(f"❌ Error reading registry: {e}")
        return []
    
    return cps

def create_cp_containers(cp_id, latitude, longitude, price, cp_num):
    """
    Create Engine and Monitor containers for a CP
    THIS IS COPIED EXACTLY FROM ev_cp_manager.py
    """
    cp_port = 6000 + cp_num
    
    engine_name = f"evcharging_cp_engine_{cp_num}"
    monitor_name = f"evcharging_cp_monitor_{cp_num}"
    
    print(f"   🔧 Creating containers for {cp_id}...")
    
    # STEP 1: Force remove any existing containers (in case they exist)
    print(f"   🗑️  Removing old containers if they exist...")
    subprocess.run(["docker", "rm", "-f", engine_name], 
                   capture_output=True, text=True)
    subprocess.run(["docker", "rm", "-f", monitor_name], 
                   capture_output=True, text=True)
    
    # STEP 2: Create Engine container (EXACTLY like cp_manager.py)
    print(f"   🚀 Creating {engine_name}...")
    engine_cmd = [
        "docker", "run", "-d",
        "--name", engine_name,
        "--network", NETWORK,
        "-p", f"{cp_port}:{cp_port}",
        "-e", "KAFKA_BROKER=kafka:9092",
        "-it",
        "evcharging-cp",
        "python", "charging_point/ev_cp_engine.py",
        cp_id, str(latitude), str(longitude), str(price),
        "central", "5000"
    ]
    
    result = subprocess.run(engine_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   ❌ Failed to create engine: {result.stderr}")
        return False
    
    print(f"   ✅ Engine created: {engine_name}")
    time.sleep(2)
    
    # STEP 3: Create Monitor container (EXACTLY like cp_manager.py)
    print(f"   🔍 Creating {monitor_name}...")
    monitor_cmd = [
        "docker", "run", "-d",
        "--name", monitor_name,
        "--network", NETWORK,
        "-e", "KAFKA_BROKER=kafka:9092",
        "-it",
        "evcharging-cp",
        "python", "charging_point/ev_cp_monitor.py",
        cp_id, engine_name, str(cp_port),
        "central", "5000"
    ]
    
    result = subprocess.run(monitor_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   ❌ Failed to create monitor: {result.stderr}")
        # Clean up engine if monitor fails
        subprocess.run(["docker", "rm", "-f", engine_name], 
                       capture_output=True, text=True)
        return False
    
    print(f"   ✅ Monitor created: {monitor_name}")
    return True

def main():
    print_header("🚀 AUTO-START CPs - Starting...")
    
    # Check if evcharging-cp image exists
    result = subprocess.run(
        ["docker", "images", "-q", "evcharging-cp"],
        capture_output=True,
        text=True
    )
    
    if not result.stdout.strip():
        print("❌ Image 'evcharging-cp' not found!")
        print("Please build it first: docker-compose build")
        return 1
    
    # Load CPs from registry
    cps = load_registry()
    
    if not cps:
        print("ℹ️  No CPs found in registry")
        print("   System will start with ZERO CPs")
        print("   Use CP Manager to create CPs: docker attach evcharging_cp_manager")
        return 0
    
    print(f"📋 Found {len(cps)} CP(s) in registry:")
    for cp in cps:
        print(f"   • {cp.get('cp_id')} at ({cp.get('latitude')}, {cp.get('longitude')})")
    
    print("\n🔨 Creating fresh containers for all CPs...\n")
    
    # Process each CP
    success_count = 0
    for cp_data in cps:
        cp_id = cp_data.get('cp_id')
        latitude = cp_data.get('latitude', '40.5')
        longitude = cp_data.get('longitude', '-3.1')
        price = cp_data.get('price_per_kwh', 0.30)
        
        try:
            cp_num = int(cp_id.split('-')[1])
        except (IndexError, ValueError):
            print(f"❌ Invalid CP ID format: {cp_id}")
            continue
        
        print(f"📍 Processing {cp_id}...")
        
        if create_cp_containers(cp_id, latitude, longitude, price, cp_num):
            success_count += 1
            print(f"✅ {cp_id} ready!\n")
        else:
            print(f"❌ {cp_id} failed!\n")
    
    # Summary
    print_header(f"✅ AUTO-START COMPLETE: {success_count}/{len(cps)} CPs ready")
    
    if success_count < len(cps):
        print("⚠️  Some CPs failed to start. Check logs above.")
        return 1
    
    print("🎉 All CPs from registry are now ACTIVATED!")
    print("\n💡 Tip: Wait 15 seconds for CPs to connect to Central")
    print("💡 Check status: docker ps")
    print("💡 View logs: docker logs evcharging_cp_engine_1")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())