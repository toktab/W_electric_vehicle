#!/usr/bin/env python3
"""
Driver WebSocket Terminal Server
Allows browser to interact with Driver via WebSocket
"""

import asyncio
import websockets
import socket
import threading
import json
import sys
from datetime import datetime

class DriverWebSocketServer:
    def __init__(self, driver_id, central_host="central", central_port=5000, ws_port=8090):
        self.driver_id = driver_id
        self.central_host = central_host
        self.central_port = central_port
        self.ws_port = ws_port
        
        self.central_socket = None
        self.running = True
        self.status = "IDLE"
        self.current_cp = None
        self.websocket_clients = set()
        
        # Colors for terminal output
        self.colors = {
            'white': '\033[37m',
            'green': '\033[92m',
            'red': '\033[91m',
            'blue': '\033[94m',
            'yellow': '\033[93m',
            'cyan': '\033[96m',
            'purple': '\033[95m',
            'reset': '\033[0m'
        }
    
    def format_output(self, text, color='white'):
        """Format text with ANSI color codes"""
        return f"{self.colors.get(color, self.colors['white'])}{text}{self.colors['reset']}"
    
    async def broadcast(self, message):
        """Send message to all connected WebSocket clients"""
        if self.websocket_clients:
            await asyncio.gather(
                *[client.send(message) for client in self.websocket_clients],
                return_exceptions=True
            )
    
    def connect_to_central(self):
        """Connect to Central system"""
        try:
            self.central_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.central_socket.connect((self.central_host, self.central_port))
            
            # Register
            from shared.protocol import Protocol, MessageTypes
            register_msg = Protocol.encode(
                Protocol.build_message(MessageTypes.REGISTER, "DRIVER", self.driver_id)
            )
            self.central_socket.send(register_msg)
            
            # Start listener thread
            thread = threading.Thread(target=self._listen_central, daemon=True)
            thread.start()
            
            return True
        except Exception as e:
            print(f"[{self.driver_id}] Failed to connect: {e}")
            return False
    
    def _listen_central(self):
        """Listen for messages from Central"""
        from shared.protocol import Protocol, MessageTypes
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
                        
                        # Handle messages and broadcast to web clients
                        asyncio.run(self._handle_central_message(msg_type, fields))
                    else:
                        break
        except Exception as e:
            asyncio.run(self.broadcast(self.format_output(f"Connection lost: {e}", 'red')))
    
    async def _handle_central_message(self, msg_type, fields):
        """Handle messages from Central and broadcast to web"""
        from shared.protocol import MessageTypes
        
        if msg_type == MessageTypes.AUTHORIZE:
            cp_id = fields[2]
            kwh_needed = fields[3]
            price = fields[4]
            
            self.status = "CHARGING"
            self.current_cp = cp_id
            
            output = f"\n{self.format_output('✅ AUTHORIZED to charge', 'green')}\n"
            output += f"{self.format_output(f'   CP: {cp_id}', 'white')}\n"
            output += f"{self.format_output(f'   kWh: {kwh_needed}, Price: {price}€/kWh', 'white')}\n"
            await self.broadcast(output)
        
        elif msg_type == MessageTypes.DENY:
            cp_id = fields[2] if len(fields) > 2 else "?"
            reason = fields[3] if len(fields) > 3 else "UNKNOWN"
            
            self.status = "IDLE"
            self.current_cp = None
            
            output = f"\n{self.format_output('❌ DENIED', 'red')}\n"
            output += f"{self.format_output(f'   CP: {cp_id}', 'white')}\n"
            output += f"{self.format_output(f'   Reason: {reason}', 'yellow')}\n"
            await self.broadcast(output)
        
        elif msg_type == MessageTypes.TICKET:
            cp_id = fields[1] if len(fields) > 1 else "?"
            total_kwh = fields[2] if len(fields) > 2 else "?"
            total_amount = fields[3] if len(fields) > 3 else "?"
            
            self.status = "IDLE"
            self.current_cp = None
            
            output = f"\n{self.format_output('═' * 60, 'cyan')}\n"
            output += f"{self.format_output('CHARGING TICKET', 'cyan')}\n"
            output += f"{self.format_output('═' * 60, 'cyan')}\n"
            output += f"{self.format_output(f'CP: {cp_id}', 'white')}\n"
            output += f"{self.format_output(f'Energy: {total_kwh} kWh', 'white')}\n"
            output += f"{self.format_output(f'Amount: {total_amount}€', 'green')}\n"
            output += f"{self.format_output('═' * 60, 'cyan')}\n"
            await self.broadcast(output)
        
        elif msg_type == MessageTypes.SUPPLY_UPDATE:
            kwh = fields[2] if len(fields) > 2 else "?"
            amount = fields[3] if len(fields) > 3 else "?"
            output = f"{self.format_output(f'⚡ Charging: {kwh} kW - {amount}€', 'blue')}\n"
            await self.broadcast(output)
        
        elif msg_type == MessageTypes.AVAILABLE_CPS:
            output = f"\n{self.format_output('Available Charging Points:', 'cyan')}\n"
            for i in range(1, len(fields), 4):
                if i + 3 < len(fields):
                    cp_id = fields[i]
                    lat = fields[i + 1]
                    lon = fields[i + 2]
                    price = fields[i + 3]
                    output += f"{self.format_output(f'  • {cp_id} (€{price}/kWh) at ({lat}, {lon})', 'white')}\n"
            await self.broadcast(output)
    
    async def handle_command(self, command):
        """Process user command"""
        from shared.protocol import Protocol, MessageTypes
        
        if command == "1":
            # Request charge
            await self.broadcast(self.format_output('\nEnter CP ID (e.g., CP-001):', 'cyan'))
            return "WAIT_CP_ID"
        
        elif command == "2":
            # View status
            output = f"\n{self.format_output('STATUS:', 'cyan')}\n"
            output += f"{self.format_output(f'  Driver ID: {self.driver_id}', 'white')}\n"
            output += f"{self.format_output(f'  Status: {self.status}', 'white')}\n"
            output += f"{self.format_output(f'  Current CP: {self.current_cp if self.current_cp else "None"}', 'white')}\n"
            await self.broadcast(output)
            return "MENU"
        
        elif command == "3":
            # Query available CPs
            query_msg = Protocol.encode(
                Protocol.build_message(MessageTypes.QUERY_AVAILABLE_CPS, self.driver_id)
            )
            try:
                self.central_socket.send(query_msg)
            except:
                await self.broadcast(self.format_output('❌ Failed to query', 'red'))
            return "MENU"
        
        elif command == "4":
            # Finish charging
            if self.status != "CHARGING":
                await self.broadcast(self.format_output(f'\n❌ Not currently charging (status: {self.status})', 'red'))
            else:
                end_msg = Protocol.encode(
                    Protocol.build_message(MessageTypes.END_CHARGE, self.driver_id, self.current_cp)
                )
                try:
                    self.central_socket.send(end_msg)
                    await self.broadcast(self.format_output('\n📤 Sent end charge request', 'green'))
                except:
                    await self.broadcast(self.format_output('❌ Failed to send request', 'red'))
            return "MENU"
        
        elif command == "help":
            await self.broadcast(self.get_help_text())
            return "MENU"
        
        elif command == "clear":
            await self.broadcast("[CLEAR]")
            return "MENU"
        
        else:
            await self.broadcast(self.format_output(f"❌ Unknown command: '{command}'", 'red'))
            return "MENU"
    
    async def handle_cp_id(self, cp_id):
        """Handle CP ID input for charging request"""
        await self.broadcast(self.format_output('Enter kWh needed (default 10):', 'cyan'))
        return "WAIT_KWH", cp_id
    
    async def handle_kwh(self, kwh_str, cp_id):
        """Handle kWh input and send request"""
        from shared.protocol import Protocol, MessageTypes
        
        try:
            kwh = float(kwh_str) if kwh_str else 10
            
            request_msg = Protocol.encode(
                Protocol.build_message(MessageTypes.REQUEST_CHARGE, self.driver_id, cp_id, kwh)
            )
            
            self.central_socket.send(request_msg)
            self.status = "REQUESTING"
            
            output = f"\n{self.format_output('📤 Requesting charge...', 'blue')}\n"
            output += f"{self.format_output(f'   CP: {cp_id}', 'white')}\n"
            output += f"{self.format_output(f'   kWh: {kwh}', 'white')}\n"
            await self.broadcast(output)
        except ValueError:
            await self.broadcast(self.format_output('❌ Invalid kWh value', 'red'))
        
        return "MENU"
    
    def get_welcome_text(self):
        """Get welcome banner"""
        return f"""{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'purple')}
{self.format_output('║', 'purple')}  {self.format_output(f'🚗 DRIVER CONSOLE - {self.driver_id}', 'cyan')}                              {self.format_output('║', 'purple')}
{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'purple')}

{self.format_output('Available Commands:', 'yellow')}
  {self.format_output('1.', 'cyan')} Request charge
  {self.format_output('2.', 'cyan')} View status
  {self.format_output('3.', 'cyan')} View available CPs
  {self.format_output('4.', 'cyan')} Finish charging
  {self.format_output('help', 'cyan')} - Show this help
  {self.format_output('clear', 'cyan')} - Clear terminal

{self.format_output('────────────────────────────────────────────────────────────', 'purple')}
"""
    
    def get_help_text(self):
        """Get help text"""
        return self.get_welcome_text()
    
    async def handle_client(self, websocket):
        """Handle WebSocket connection from browser"""
        self.websocket_clients.add(websocket)
        
        # Send welcome message
        await websocket.send(self.get_welcome_text())
        
        state = "MENU"
        temp_data = {}
        
        try:
            async for message in websocket:
                command = message.strip()
                
                if not command:
                    continue
                
                # Echo command
                await websocket.send(f"$ {command}")
                
                # Process based on state
                if state == "MENU":
                    result = await self.handle_command(command)
                    if isinstance(result, tuple):
                        state = result[0]
                        temp_data['cp_id'] = result[1]
                    else:
                        state = result
                
                elif state == "WAIT_CP_ID":
                    result = await self.handle_cp_id(command)
                    state = result[0]
                    temp_data['cp_id'] = result[1]
                
                elif state == "WAIT_KWH":
                    state = await self.handle_kwh(command, temp_data.get('cp_id'))
        
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.websocket_clients.remove(websocket)
    
    async def start_websocket_server(self):
        """Start WebSocket server"""
        print(f"[{self.driver_id}] Starting WebSocket server on port {self.ws_port}...")
        async with websockets.serve(self.handle_client, "0.0.0.0", self.ws_port):
            await asyncio.Future()  # Run forever

def main():
    if len(sys.argv) < 2:
        print("Usage: python driver_websocket.py <DRIVER_ID> [central_host] [central_port] [ws_port]")
        sys.exit(1)
    
    driver_id = sys.argv[1]
    central_host = sys.argv[2] if len(sys.argv) > 2 else "central"
    central_port = int(sys.argv[3]) if len(sys.argv) > 3 else 5000
    ws_port = int(sys.argv[4]) if len(sys.argv) > 4 else 8090
    
    server = DriverWebSocketServer(driver_id, central_host, central_port, ws_port)
    
    # Connect to Central
    if not server.connect_to_central():
        print(f"[{driver_id}] Failed to connect to Central")
        sys.exit(1)
    
    print(f"[{driver_id}] Connected to Central at {central_host}:{central_port}")
    print(f"[{driver_id}] WebSocket URL: ws://localhost:{ws_port}")
    
    # Start WebSocket server
    asyncio.run(server.start_websocket_server())

if __name__ == "__main__":
    main()