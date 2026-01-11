#!/usr/bin/env python3
"""
CP Monitor WebSocket Terminal Server
Allows browser to interact with CP Monitor via WebSocket
"""

import asyncio
import websockets
import socket
import threading
import sys
from datetime import datetime

class MonitorWebSocketServer:
    def __init__(self, cp_id, engine_host="localhost", engine_port=6001, 
                 central_host="central", central_port=5000, ws_port=9000):
        self.cp_id = cp_id
        self.engine_host = engine_host
        self.engine_port = engine_port
        self.central_host = central_host
        self.central_port = central_port
        self.ws_port = ws_port
        
        self.engine_socket = None
        self.central_socket = None
        self.running = True
        self.websocket_clients = set()
        
        # Status tracking
        self.engine_healthy = True
        self.current_driver = None
        self.charging_active = False
        self.charge_progress = 0
        
        self.colors = {
            'white': '\033[37m', 'green': '\033[92m', 'red': '\033[91m',
            'blue': '\033[94m', 'yellow': '\033[93m', 'cyan': '\033[96m',
            'purple': '\033[95m', 'reset': '\033[0m'
        }
    
    def format_output(self, text, color='white'):
        return f"{self.colors.get(color, self.colors['white'])}{text}{self.colors['reset']}"
    
    async def broadcast(self, message):
        """Send message to all connected WebSocket clients"""
        if self.websocket_clients:
            await asyncio.gather(
                *[client.send(message) for client in self.websocket_clients],
                return_exceptions=True
            )
    
    def connect_to_engine(self):
        """Connect to CP Engine"""
        try:
            self.engine_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.engine_socket.connect((self.engine_host, self.engine_port))
            print(f"[{self.cp_id} Monitor] ✅ Connected to Engine")
            return True
        except Exception as e:
            print(f"[{self.cp_id} Monitor] Failed to connect to Engine: {e}")
            return False
    
    def connect_to_central(self):
        """Connect to Central system"""
        try:
            self.central_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.central_socket.connect((self.central_host, self.central_port))
            
            from shared.protocol import Protocol, MessageTypes
            register_msg = Protocol.encode(
                Protocol.build_message(MessageTypes.REGISTER, "MONITOR", self.cp_id, self.cp_id)
            )
            self.central_socket.send(register_msg)
            
            # Start listener thread
            thread = threading.Thread(target=self._listen_central, daemon=True)
            thread.start()
            
            print(f"[{self.cp_id} Monitor] ✅ Connected to Central")
            return True
        except Exception as e:
            print(f"[{self.cp_id} Monitor] Failed to connect to Central: {e}")
            return False
    
    def _listen_central(self):
        """Listen for messages from Central"""
        from shared.protocol import Protocol
        buffer = b''
        
        try:
            while self.running:
                data = self.central_socket.recv(4096)
                if not data:
                    break
                
                buffer += data
                
                while len(buffer) > 0:
                    message, is_valid = Protocol.decode(buffer)
                    
                    if is_valid:
                        etx_pos = buffer.find(b'\x03')
                        buffer = buffer[etx_pos + 2:]
                        
                        fields = Protocol.parse_message(message)
                        msg_type = fields[0]
                        
                        asyncio.run(self._handle_central_message(msg_type, fields))
                    else:
                        break
        except Exception as e:
            asyncio.run(self.broadcast(self.format_output(f"Central connection lost: {e}", 'red')))
    
    async def _handle_central_message(self, msg_type, fields):
        """Handle messages from Central"""
        if msg_type == "DRIVER_START":
            driver_id = fields[2] if len(fields) > 2 else "?"
            self.current_driver = driver_id
            self.charging_active = True
            self.charge_progress = 0
            
            output = f"\n{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'green')}\n"
            output += f"{self.format_output('║  🚗  DRIVER CONNECTED - CHARGING SESSION STARTED  ⚡         ║', 'green')}\n"
            output += f"{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'green')}\n"
            output += f"{self.format_output(f'Driver: {driver_id}', 'white')}\n"
            await self.broadcast(output)
        
        elif msg_type == "CHARGING_COMPLETE":
            self.charge_progress = 100
            output = f"\n{self.format_output('🎉  CHARGING COMPLETE - 100% REACHED!  🔋', 'green')}\n"
            await self.broadcast(output)
        
        elif msg_type == "DRIVER_STOP":
            driver_id = fields[2] if len(fields) > 2 else "?"
            output = f"\n{self.format_output('✅  VEHICLE UNPLUGGED - SESSION COMPLETE  🔌', 'green')}\n"
            await self.broadcast(output)
            self.current_driver = None
            self.charging_active = False
            self.charge_progress = 0
    
    async def handle_command(self, command):
        """Process user command"""
        if command == "status":
            output = f"\n{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'cyan')}\n"
            output += f"{self.format_output(f'║  {self.cp_id} MONITOR STATUS', 'cyan')}\n"
            output += f"{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'cyan')}\n"
            
            engine_icon = "💚" if self.engine_healthy else "🔴"
            engine_text = "HEALTHY" if self.engine_healthy else "FAULTY"
            
            output += f"{self.format_output(f'Engine Status: {engine_text} {engine_icon}', 'white')}\n"
            
            if self.charging_active:
                status_text = "CHARGING IN PROGRESS"
                status_icon = "⚡"
            else:
                status_text = "AVAILABLE"
                status_icon = "🟢"
            
            output += f"{self.format_output(f'Point Status: {status_text} {status_icon}', 'white')}\n"
            
            if self.current_driver:
                output += f"{self.format_output(f'Current Driver: {self.current_driver}', 'white')}\n"
                output += f"{self.format_output(f'Progress: {self.charge_progress}%', 'white')}\n"
            
            await self.broadcast(output)
        
        elif command == "help":
            await self.broadcast(self.get_help_text())
        
        elif command == "clear":
            await self.broadcast("[CLEAR]")
        
        else:
            await self.broadcast(self.format_output(f"❌ Unknown command: '{command}'", 'red'))
    
    def get_welcome_text(self):
        return f"""{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'purple')}
{self.format_output('║', 'purple')}  {self.format_output(f'🔍 CP MONITOR - {self.cp_id}', 'cyan')}                                    {self.format_output('║', 'purple')}
{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'purple')}

{self.format_output('Available Commands:', 'yellow')}
  {self.format_output('status', 'cyan')} - View current status and health
  {self.format_output('help', 'cyan')}   - Show this help
  {self.format_output('clear', 'cyan')}  - Clear terminal

{self.format_output('Monitoring engine health and driver connections...', 'green')}
{self.format_output('────────────────────────────────────────────────────────────', 'purple')}
"""
    
    def get_help_text(self):
        return self.get_welcome_text()
    
    async def handle_client(self, websocket):
        """Handle WebSocket connection from browser"""
        self.websocket_clients.add(websocket)
        await websocket.send(self.get_welcome_text())
        
        try:
            async for message in websocket:
                command = message.strip()
                if not command:
                    continue
                
                await websocket.send(f"$ {command}")
                await self.handle_command(command)
        
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.websocket_clients.remove(websocket)
    
    async def start_websocket_server(self):
        """Start WebSocket server"""
        print(f"[{self.cp_id} Monitor] Starting WebSocket server on port {self.ws_port}...")
        async with websockets.serve(self.handle_client, "0.0.0.0", self.ws_port):
            await asyncio.Future()

def main():
    if len(sys.argv) < 2:
        print("Usage: python monitor_websocket.py <CP_ID> [engine_host] [engine_port] [central_host] [central_port] [ws_port]")
        sys.exit(1)
    
    cp_id = sys.argv[1]
    engine_host = sys.argv[2] if len(sys.argv) > 2 else "localhost"
    engine_port = int(sys.argv[3]) if len(sys.argv) > 3 else 6001
    central_host = sys.argv[4] if len(sys.argv) > 4 else "central"
    central_port = int(sys.argv[5]) if len(sys.argv) > 5 else 5000
    ws_port = int(sys.argv[6]) if len(sys.argv) > 6 else 9000
    
    server = MonitorWebSocketServer(cp_id, engine_host, engine_port, central_host, central_port, ws_port)
    
    if not server.connect_to_engine():
        print(f"[{cp_id}] Failed to connect to Engine")
    
    if not server.connect_to_central():
        print(f"[{cp_id}] Failed to connect to Central")
    
    print(f"[{cp_id} Monitor] WebSocket URL: ws://localhost:{ws_port}")
    asyncio.run(server.start_websocket_server())

if __name__ == "__main__":
    main()