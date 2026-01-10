#!/usr/bin/env python3
"""
CP Manager - WebSocket Terminal Server
Allows browser to interact with CP Manager via WebSocket
"""

import asyncio
import websockets
import requests
import subprocess
import json
import sys
from datetime import datetime

REGISTRY_URL = "http://registry:5001"
PORT = 8082

class CPManagerTerminal:
    def __init__(self):
        self.state = 'MENU'
        self.temp_data = {}
        self.network_name = None
        self._detect_network()
    
    def _detect_network(self):
        """Detect the Docker network that Central is using"""
        try:
            result = subprocess.run(
                ["docker", "inspect", "evcharging_central", 
                 "--format", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}"],
                capture_output=True,
                text=True
            )
            self.network_name = result.stdout.strip()
            if not self.network_name:
                # Fallback: try to find any network with 'evcharging' in name
                result = subprocess.run(
                    ["docker", "network", "ls", "--filter", "name=evcharging", 
                     "--format", "{{.Name}}"],
                    capture_output=True,
                    text=True
                )
                networks = result.stdout.strip().split('\n')
                self.network_name = networks[0] if networks else "bridge"
            
            print(f"[CPManager] Detected network: {self.network_name}")
        except Exception as e:
            print(f"[CPManager] Network detection failed: {e}")
            self.network_name = "bridge"
    
    def format_output(self, text, color='white'):
        """Format text with ANSI color codes"""
        colors = {
            'white': '\033[37m',
            'green': '\033[92m',
            'red': '\033[91m',
            'blue': '\033[94m',
            'yellow': '\033[93m',
            'cyan': '\033[96m',
            'purple': '\033[95m',
            'reset': '\033[0m'
        }
        return f"{colors.get(color, colors['white'])}{text}{colors['reset']}"
    
    def get_welcome_message(self):
        """Return welcome banner"""
        return f"""{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'purple')}
{self.format_output('║', 'purple')}  {self.format_output('🔧 CP MANAGER', 'cyan')} - Control Panel                           {self.format_output('║', 'purple')}
{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'purple')}

{self.format_output('Available Commands:', 'yellow')}
  {self.format_output('1.', 'cyan')} Create new CP
  {self.format_output('2.', 'cyan')} Delete CP
  {self.format_output('3.', 'cyan')} List all CPs
  {self.format_output('4.', 'cyan')} View CP status
  {self.format_output('clear', 'cyan')} - Clear terminal
  {self.format_output('help', 'cyan')} - Show this help

{self.format_output('Network:', 'yellow')} {self.format_output(self.network_name, 'green')}
{self.format_output('────────────────────────────────────────────────────────────', 'purple')}
"""
    
    async def process_command(self, command):
        """Process user command and return response"""
        if self.state == 'MENU':
            return await self.handle_menu_command(command)
        elif self.state == 'CREATE_ID':
            self.temp_data['cpId'] = command
            self.state = 'CREATE_LAT'
            return self.format_output('Enter latitude (default 40.5):', 'cyan')
        elif self.state == 'CREATE_LAT':
            self.temp_data['lat'] = command or '40.5'
            self.state = 'CREATE_LON'
            return self.format_output('Enter longitude (default -3.1):', 'cyan')
        elif self.state == 'CREATE_LON':
            self.temp_data['lon'] = command or '-3.1'
            self.state = 'CREATE_PRICE'
            return self.format_output('Enter price €/kWh (default 0.30):', 'cyan')
        elif self.state == 'CREATE_PRICE':
            self.temp_data['price'] = command or '0.30'
            result = await self.execute_create_cp()
            self.state = 'MENU'
            return result
        elif self.state == 'DELETE_ID':
            result = await self.execute_delete_cp(command)
            self.state = 'MENU'
            return result
    
    async def handle_menu_command(self, command):
        """Handle commands in main menu"""
        if command == '1':
            self.state = 'CREATE_ID'
            self.temp_data = {}
            return f"""\n{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'purple')}
{self.format_output('║', 'purple')}  CREATE NEW CHARGING POINT                                  {self.format_output('║', 'purple')}
{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'purple')}

{self.format_output('Enter CP ID (e.g., CP-010):', 'cyan')}"""
        
        elif command == '2':
            self.state = 'DELETE_ID'
            return f"""\n{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'red')}
{self.format_output('║', 'red')}  DELETE CHARGING POINT                                      {self.format_output('║', 'red')}
{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'red')}

{self.format_output('Enter CP ID to delete (e.g., CP-010):', 'cyan')}"""
        
        elif command == '3':
            return await self.show_cp_list()
        
        elif command == '4':
            return await self.show_cp_status()
        
        elif command == 'help':
            return self.get_welcome_message()
        
        elif command == 'clear':
            return '[CLEAR]'
        
        else:
            return self.format_output(f"❌ Unknown command: '{command}'. Type 'help' for available commands.", 'red')
    
    async def execute_create_cp(self):
        """Create new CP"""
        cp_id = self.temp_data['cpId']
        lat = self.temp_data['lat']
        lon = self.temp_data['lon']
        price = self.temp_data['price']
        
        output = f"\n{self.format_output('📝 Step 1/3: Registering in Registry...', 'blue')}\n"
        
        try:
            # Extract CP number
            cp_num = int(cp_id.split('-')[1])
            
            # Register in Registry
            response = requests.post(
                f"{REGISTRY_URL}/register",
                json={
                    "cp_id": cp_id,
                    "latitude": lat,
                    "longitude": lon,
                    "price_per_kwh": float(price)
                },
                timeout=10
            )
            
            if response.status_code == 201:
                data = response.json()
                output += self.format_output('✅ Registered successfully!', 'green') + "\n"
                output += self.format_output(f"   Username: {data['username']}", 'white') + "\n"
                output += self.format_output(f"   Password: {data['password']}", 'white') + "\n"
                
                # Replace the credentials saving section (around line 220) with this:

                # 🔥 SAVE CREDENTIALS LOCALLY
                credentials = {
                    "username": data['username'],
                    "password": data['password']
                }
                
                try:
                    import os
                    import json
                    
                    # Debug: Print current working directory
                    cwd = os.getcwd()
                    print(f"\n[DEBUG] Current working directory: {cwd}")
                    
                    # Create data directory
                    os.makedirs('/app/data', exist_ok=True)
                    print(f"[DEBUG] Created/verified /app/data directory")
                    
                    # Define credentials file path
                    creds_file = f"/app/data/{cp_id}_credentials.json"
                    print(f"[DEBUG] Credentials file path: {creds_file}")
                    
                    # Write credentials
                    with open(creds_file, 'w') as f:
                        json.dump(credentials, f, indent=2)
                    
                    # Verify file exists
                    if os.path.exists(creds_file):
                        file_size = os.path.getsize(creds_file)
                        print(f"[DEBUG] ✅ File created successfully: {creds_file} ({file_size} bytes)")
                        output += self.format_output(f'   💾 Credentials saved to {creds_file}', 'cyan') + "\n"
                    else:
                        print(f"[DEBUG] ❌ File NOT found after writing!")
                        output += self.format_output(f'   ⚠️  File not found after writing!', 'red') + "\n"
                        
                except Exception as e:
                    print(f"[DEBUG] ❌ Exception saving credentials: {e}")
                    import traceback
                    traceback.print_exc()
                    output += self.format_output(f'   ⚠️  Failed to save credentials: {e}', 'yellow') + "\n"
                
            else:
                error = response.json()
                raise Exception(error.get('error', 'Registration failed'))
            
            # Wait for Central
            output += f"\n{self.format_output('⏳ Step 2/3: Waiting for Central (15s)...', 'blue')}\n"
            await asyncio.sleep(15)
            output += self.format_output('✅ Central detected CP!', 'green') + "\n"
            
            # Launch containers
            output += f"\n{self.format_output('🚀 Step 3/3: Launching containers...', 'blue')}\n"
            output += self.format_output(f"   📡 Network: {self.network_name}", 'cyan') + "\n"
            
            cp_port = 6000 + cp_num
            engine_name = f"evcharging_cp_engine_{cp_num}"
            monitor_name = f"evcharging_cp_monitor_{cp_num}"
            
            # Remove old containers
            subprocess.run(["docker", "rm", "-f", engine_name], capture_output=True)
            subprocess.run(["docker", "rm", "-f", monitor_name], capture_output=True)
            
            # Get absolute path to data folder
            import os
            data_path = os.path.abspath("data")
            
            # Create Engine with CORRECT network and DATA VOLUME
            output += self.format_output(f"   🔧 Creating {engine_name}...", 'white') + "\n"
            engine_cmd = [
                "docker", "run", "-d",
                "--name", engine_name,
                "--network", self.network_name,
                "-p", f"{cp_port}:{cp_port}",
                "-e", "KAFKA_BROKER=kafka:9092",
                "-v", f"{data_path}:/app/data",  # 🔥 MOUNT DATA FOLDER
                "-it", "evcharging-cp",
                "python", "charging_point/ev_cp_engine.py",
                cp_id, str(lat), str(lon), str(price), "central", "5000"
            ]
            
            result = subprocess.run(engine_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                output += self.format_output('   ✅ Engine created', 'green') + "\n"
            else:
                raise Exception(f"Engine failed: {result.stderr}")
            
            await asyncio.sleep(2)
            
            # Create Monitor with CORRECT network and DATA VOLUME
            output += self.format_output(f"   🔍 Creating {monitor_name}...", 'white') + "\n"
            monitor_cmd = [
                "docker", "run", "-d",
                "--name", monitor_name,
                "--network", self.network_name,
                "-e", "KAFKA_BROKER=kafka:9092",
                "-v", f"{data_path}:/app/data",  # 🔥 MOUNT DATA FOLDER
                "-it", "evcharging-cp",
                "python", "charging_point/ev_cp_monitor.py",
                cp_id, engine_name, str(cp_port), "central", "5000"
            ]
            
            result = subprocess.run(monitor_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                output += self.format_output('   ✅ Monitor created', 'green') + "\n"
            else:
                raise Exception(f"Monitor failed: {result.stderr}")
            
            output += f"\n{self.format_output('⏳ Waiting 10s for authentication...', 'blue')}\n"
            await asyncio.sleep(10)
            
            output += f"\n{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'green')}\n"
            output += f"{self.format_output('║', 'green')}  {self.format_output(f'✅ {cp_id} READY FOR CHARGING!', 'green')}                               {self.format_output('║', 'green')}\n"
            output += f"{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'green')}\n"
            output += f"\n{self.format_output('💡 Refresh the dashboard to see it ACTIVATED!', 'cyan')}\n"
            output += f"\n{self.format_output(f'💾 Credentials saved: data/{cp_id}_credentials.json', 'cyan')}\n"
            
        except Exception as e:
            output += f"\n{self.format_output(f'❌ Error: {e}', 'red')}\n"
        
        output += f"{self.format_output('────────────────────────────────────────────────────────────', 'purple')}\n"
        return output
    
    async def execute_delete_cp(self, cp_id):
        """Delete CP"""
        output = ""
        
        try:
            cp_num = int(cp_id.split('-')[1])
            
            output += f"\n{self.format_output('🛑 Step 1/2: Stopping containers...', 'yellow')}\n"
            
            engine_name = f"evcharging_cp_engine_{cp_num}"
            monitor_name = f"evcharging_cp_monitor_{cp_num}"
            
            subprocess.run(["docker", "stop", engine_name], capture_output=True)
            subprocess.run(["docker", "stop", monitor_name], capture_output=True)
            subprocess.run(["docker", "rm", engine_name], capture_output=True)
            subprocess.run(["docker", "rm", monitor_name], capture_output=True)
            
            output += self.format_output('   ✅ Containers removed', 'green') + "\n"
            
            output += f"\n{self.format_output('📝 Step 2/2: Unregistering from Registry...', 'blue')}\n"
            
            response = requests.delete(f"{REGISTRY_URL}/unregister/{cp_id}", timeout=10)
            if response.status_code == 200:
                output += self.format_output('   ✅ Unregistered', 'green') + "\n"
            
            output += f"\n{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'green')}\n"
            output += f"{self.format_output('║', 'green')}  {self.format_output(f'✅ {cp_id} COMPLETELY DELETED', 'green')}                               {self.format_output('║', 'green')}\n"
            output += f"{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'green')}\n"
            
        except Exception as e:
            output += f"\n{self.format_output(f'❌ Error: {e}', 'red')}\n"
        
        output += f"{self.format_output('────────────────────────────────────────────────────────────', 'purple')}\n"
        return output
    
    async def show_cp_list(self):
        """List all CPs"""
        output = f"\n{self.format_output('📋 Fetching registered CPs...', 'blue')}\n"
        
        try:
            response = requests.get(f"{REGISTRY_URL}/list", timeout=10)
            data = response.json()
            cps = data.get('charging_points', [])
            
            if not cps:
                output += f"\n{self.format_output('No charging points registered', 'yellow')}\n"
            else:
                output += f"\n{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'cyan')}\n"
                output += f"{self.format_output('║', 'cyan')}  ALL REGISTERED CHARGING POINTS                             {self.format_output('║', 'cyan')}\n"
                output += f"{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'cyan')}\n\n"
                
                for i, cp in enumerate(cps, 1):
                    output += self.format_output(f"{i}. {cp['cp_id']}", 'green') + "\n"
                    output += self.format_output(f"   Location: ({cp['latitude']}, {cp['longitude']})", 'white') + "\n"
                    output += self.format_output(f"   Username: {cp['username']}", 'white') + "\n"
                    output += self.format_output(f"   Registered: {cp['registered_at'][:19]}", 'white') + "\n\n"
        
        except Exception as e:
            output += self.format_output(f'❌ Error: {e}', 'red') + "\n"
        
        output += f"{self.format_output('────────────────────────────────────────────────────────────', 'purple')}\n"
        return output
    
    async def show_cp_status(self):
        """Show Docker container status"""
        output = f"\n{self.format_output('📊 Docker Container Status:', 'blue')}\n\n"
        
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=evcharging_cp_", 
                 "--format", "{{.Names}}\t{{.Status}}"],
                capture_output=True,
                text=True
            )
            
            if result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
                    if '\t' in line:
                        name, status = line.split('\t', 1)
                        output += self.format_output(f"  • {name}", 'green') + "\n"
                        output += self.format_output(f"    {status}", 'white') + "\n"
            else:
                output += self.format_output('No CP containers running', 'yellow') + "\n"
        
        except Exception as e:
            output += self.format_output(f'❌ Error: {e}', 'red') + "\n"
        
        output += f"\n{self.format_output('────────────────────────────────────────────────────────────', 'purple')}\n"
        return output


async def handle_client(websocket):
    """Handle WebSocket connection from browser"""
    terminal = CPManagerTerminal()
    
    # Send welcome message
    await websocket.send(terminal.get_welcome_message())
    
    try:
        async for message in websocket:
            command = message.strip()
            
            if command:
                # Echo command
                await websocket.send(f"$ {command}")
                
                # Process and send response
                response = await terminal.process_command(command)
                await websocket.send(response)
    
    except websockets.exceptions.ConnectionClosed:
        pass


async def main():
    print("=" * 70)
    print("  CP Manager WebSocket Server - STARTED")
    print("=" * 70)
    print(f"\n  WebSocket URL: ws://localhost:{PORT}")
    print("  Waiting for browser connections...\n")
    
    async with websockets.serve(handle_client, "0.0.0.0", PORT):
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())