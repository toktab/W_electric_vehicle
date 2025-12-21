#!/usr/bin/env python3
"""
Auto-Start CPs - Automatically recreate/start all CPs from registry on system startup
This creates the illusion that CPs persist across restarts!
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

def check_container_exists(container_name):
    """Check if a Docker container exists (running or stopped)"""
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True
    )
    return container_name in result.stdout

def check_container_running(container_name):
    """Check if a Docker container is running"""
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True
    )
    return container_name in result.stdout

def start_container(container_name):
    """Start an existing stopped container"""
    result = subprocess.run(
        ["docker", "start", container_name],
        capture_output=True,
        text=True
    )
    return result.returncode == 0

def create_cp_containers(cp_id, latitude, longitude, price, cp_num):
    """Create Engine and Monitor containers for a CP"""
    cp_port = 6000 + cp_num
    
    engine_name = f"evcharging_cp_engine_{cp_num}"
    monitor_name = f"evcharging_cp_monitor_{cp_num}"
    
    print(f"   🔧 Creating containers for {cp_id}...")
    
    # Remove old containers if they exist (force remove even if running)
    subprocess.run(["docker", "rm", "-f", engine_name], 
                   capture_output=True, text=True)
    subprocess.run(["docker", "rm", "-f", monitor_name], 
                   capture_output=True, text=True)
    
    # Create Engine container
    engine_cmd = [
        "docker", "run", "-d",
        "--name", engine_name,
        "--network", NETWORK,
        "-p", f"{cp_port}:{cp_port}",
        "-e", "KAFKA_BROKER=kafka:9092",
        "evcharging-cp",
        "python", "charging_point/ev_cp_engine.py",
        cp_id, str(latitude), str(longitude), str(price),
        "central", "5000"
    ]
    
    result = subprocess.run(engine_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   ❌ Failed to create engine: {result.stderr}")
        return False
    
    print(f"   ✅ Engine created")
    time.sleep(2)
    
    # Create Monitor container
    monitor_cmd = [
        "docker", "run", "-d",
        "--name", monitor_name,
        "--network", NETWORK,
        "-e", "KAFKA_BROKER=kafka:9092",
        "evcharging-cp",
        "python", "charging_point/ev_cp_monitor.py",
        cp_id, engine_name, str(cp_port),
        "central", "5000"
    ]
    
    result = subprocess.run(monitor_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   ❌ Failed to create monitor: {result.stderr}")
        return False
    
    print(f"   ✅ Monitor created")
    return True

def process_cp(cp_data):
    """Process a single CP: check if containers exist, create/start as needed"""
    cp_id = cp_data.get('cp_id')
    latitude = cp_data.get('latitude', '40.5')
    longitude = cp_data.get('longitude', '-3.1')
    price = cp_data.get('price_per_kwh', 0.30)
    
    try:
        cp_num = int(cp_id.split('-')[1])
    except (IndexError, ValueError):
        print(f"❌ Invalid CP ID format: {cp_id}")
        return False
    
    engine_name = f"evcharging_cp_engine_{cp_num}"
    monitor_name = f"evcharging_cp_monitor_{cp_num}"
    
    print(f"\n📍 Processing {cp_id} at ({latitude}, {longitude})")
    
    # Check Engine container
    engine_exists = check_container_exists(engine_name)
    engine_running = check_container_running(engine_name)
    
    # Check Monitor container
    monitor_exists = check_container_exists(monitor_name)
    monitor_running = check_container_running(monitor_name)
    
    # Decision tree
    if engine_exists and monitor_exists:
        if engine_running and monitor_running:
            print(f"   ✅ Containers already running")
            return True
        else:
            # Containers exist but stopped - start them
            print(f"   🔄 Containers exist but stopped, starting...")
            
            if not engine_running:
                if start_container(engine_name):
                    print(f"   ✅ Engine started")
                else:
                    print(f"   ❌ Failed to start engine")
                    return False
            
            time.sleep(2)
            
            if not monitor_running:
                if start_container(monitor_name):
                    print(f"   ✅ Monitor started")
                else:
                    print(f"   ❌ Failed to start monitor")
                    return False
            
            return True
    else:
        # Containers don't exist - create them
        print(f"   🆕 Containers don't exist, creating...")
        return create_cp_containers(cp_id, latitude, longitude, price, cp_num)

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
    
    # Process each CP
    success_count = 0
    for cp_data in cps:
        if process_cp(cp_data):
            success_count += 1
    
    # Summary
    print_header(f"✅ AUTO-START COMPLETE: {success_count}/{len(cps)} CPs ready")
    
    if success_count < len(cps):
        print("⚠️  Some CPs failed to start. Check logs above.")
        return 1
    
    print("🎉 All CPs from registry are now ACTIVATED!")
    print("\n💡 Tip: Wait 15 seconds for CPs to connect to Central")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())