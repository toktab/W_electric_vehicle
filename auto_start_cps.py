#!/usr/bin/env python3
"""
Auto-Start CPs - WITH PROPER ENCODING
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

def get_container_logs(container_name, lines=20):
    """Get container logs with proper encoding handling"""
    try:
        # Use UTF-8 encoding explicitly
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container_name],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'  # Replace problematic characters
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"Error reading logs: {e}"

def is_container_running(container_name):
    """Check if container is running"""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"],
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        return bool(result.stdout.strip())
    except:
        return False

def create_cp_containers(cp_id, latitude, longitude, price, cp_num):
    """Create Engine and Monitor containers for a CP"""
    cp_port = 6000 + cp_num
    
    engine_name = f"evcharging_cp_engine_{cp_num}"
    monitor_name = f"evcharging_cp_monitor_{cp_num}"
    
    print(f"   🔧 Creating containers for {cp_id}...")
    
    # STEP 1: Force remove any existing containers
    print(f"   🗑️  Removing old containers if they exist...")
    subprocess.run(["docker", "rm", "-f", engine_name], 
                   capture_output=True, text=True)
    subprocess.run(["docker", "rm", "-f", monitor_name], 
                   capture_output=True, text=True)
    
    # STEP 2: Create Engine container
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
    
    result = subprocess.run(engine_cmd, capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        print(f"   ❌ Failed to create engine: {result.stderr}")
        return False
    
    print(f"   ✅ Engine created: {engine_name}")
    time.sleep(3)
    
    # STEP 3: Create Monitor container
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
    
    result = subprocess.run(monitor_cmd, capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        print(f"   ❌ Failed to create monitor: {result.stderr}")
        subprocess.run(["docker", "rm", "-f", engine_name], 
                       capture_output=True, text=True)
        return False
    
    print(f"   ✅ Monitor created: {monitor_name}")
    
    # STEP 4: Wait and check if both containers are still running
    print(f"   ⏳ Waiting 5 seconds to verify containers...")
    time.sleep(5)
    
    engine_running = is_container_running(engine_name)
    monitor_running = is_container_running(monitor_name)
    
    if not engine_running:
        print(f"   ❌ WARNING: Engine {engine_name} stopped!")
        print(f"   📋 Engine logs:")
        print(get_container_logs(engine_name))
        return False
    
    if not monitor_running:
        print(f"   ❌ WARNING: Monitor {monitor_name} stopped!")
        print(f"   📋 Monitor logs:")
        print(get_container_logs(monitor_name))
        return False
    
    print(f"   ✅ Both containers running successfully")
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
    print("\n💡 Check status: docker ps")
    print("💡 View engine logs: docker logs evcharging_cp_engine_1")
    print("💡 View monitor logs: docker logs evcharging_cp_monitor_1")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())