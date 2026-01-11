#!/usr/bin/env python3
"""
CP Engine WebSocket Terminal Server
Allows browser to interact with CP Engine via WebSocket
"""

import asyncio
import websockets
import socket
import threading
import sys
import time
from datetime import datetime

class EngineWebSocketServer:
    def __init__(self, cp_id, latitude, longitude, price_per_kwh,
                 central_host="central", central_port=5000, ws_port=9100):
        self.cp_id = cp_id
        self.latitude = latitude
        self.longitude = longitude
        self.price_per_kwh = float(price_per_kwh)
        self.central_host = central_host
        self.central_port = central_port
        self.ws_port = ws_port
        
        self.central_socket = None
        self.running = True
        self.websocket_clients = set()
        
        self.state = "ACTIVATED"
        self.current_driver = None
        self.current_session = None
        self.charging_complete = False
        
        self.colors = {
            'white': '\033[37m', 'green': '\033[92m', 'red': '\033[91m',
            'blue': '\033[94m', 'yellow': '\033[93m', 'cyan': '\033[96m',
            'purple': '\033[95m', 'reset': '\033[0m'
        }
    
    def format_output(self, text, color='white'):
        return f"{self.colors.get(color, self.colors['white'])}{text}{self.colors['reset']}"
    
    async def broadcast(self, message):
        if self.websocket_clients:
            await asyncio.gather(
                *[client.send(message) for client in self.websocket_clients],
                return_exceptions=True
            )
    
    def connect_to_central(self):
        try:
            self.central_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.central_socket.connect((self.central_host, self.central_port))
            
            from shared.protocol import Protocol, MessageTypes
            register_msg = Protocol.encode(
                Protocol.build_message(MessageTypes.REGISTER, "CP", self.cp_id,
                                     self.latitude, self.longitude, self.price_per_kwh)
            )
            self.central_socket.send(register_msg)
            
            thread = threading.Thread(target=self._listen_central, daemon=True)
            thread.start()
            
            print(f"[{self.cp_id} Engine] ✅ Connected to Central")
            return True
        except Exception as e:
            print(f"[{self.cp_id} Engine] Failed to connect: {e}")
            return False
    
    def _listen_central(self):
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
            asyncio.run(self.broadcast(self.format_output(f"Connection lost: {e}", 'red')))
    
    async def _handle_central_message(self, msg_type, fields):
        from shared.protocol import MessageTypes
        
        if msg_type == MessageTypes.AUTHORIZE:
            driver_id = fields[1]
            kwh_needed = float(fields[3]) if len(fields) > 3 else 10
            
            self.current_driver = driver_id
            self.state = "SUPPLYING"
            self.charging_complete = False
            self.current_session = {
                "driver_id": driver_id,
                "start_time": time.time(),
                "kwh_needed": kwh_needed,
                "kwh_delivered": 0.0,
                "amount": 0.0
            }
            
            output = f"\n{self.format_output('✅ Charging authorized', 'green')}\n"
            output += f"{self.format_output(f'   Driver: {driver_id}', 'white')}\n"
            output += f"{self.format_output(f'   kWh Needed: {kwh_needed}', 'white')}\n"
            output += f"{self.format_output('   → IN USE - CHARGING', 'blue')}\n"
            await self.broadcast(output)
        
        elif msg_type == MessageTypes.STOP_COMMAND:
            self.state = "STOPPED"
            output = f"{self.format_output('⚠️  Received STOP command from CENTRAL - now stopped', 'yellow')}\n"
            await self.broadcast(output)
        
        elif msg_type == MessageTypes.RESUME_COMMAND:
            self.state = "ACTIVATED"
            self.charging_complete = False
            output = f"{self.format_output('✅ Received RESUME command from CENTRAL - now activated', 'green')}\n"
            await self.broadcast(output)
        
        elif msg_type == MessageTypes.END_SUPPLY:
            output = f"{self.format_output('🔌 Supply ended by CENTRAL', 'yellow')}\n"
            await self.broadcast(output)
            self.state = "ACTIVATED"
            self.current_driver = None
            self.current_session = None
            self.charging_complete = False
    
    async def handle_command(self, command):
        from shared.protocol import Protocol, MessageTypes
        
        if command == "1":
            # Request charge for driver
            await self.broadcast(self.format_output('\nEnter Driver ID (e.g., DRIVER-001):', 'cyan'))
            return "WAIT_DRIVER_ID"
        
        elif command == "2":
            # View status
            output = f"\n{self.format_output('STATUS:', 'cyan')}\n"
            output += f"{self.format_output(f'  CP ID: {self.cp_id}', 'white')}\n"
            output += f"{self.format_output(f'  State: {self.state}', 'white')}\n"
            output += f"{self.format_output(f'  Current Driver: {self.current_driver or "None"}', 'white')}\n"
            
            if self.current_session:
                output += f"{self.format_output(f'  kWh Delivered: {self.current_session["kwh_delivered"]:.2f}', 'white')}\n"
                output += f"{self.format_output(f'  Amount: {self.current_session["amount"]:.2f}€', 'white')}\n"
            
            await self.broadcast(output)
            return "MENU"
        
        elif command == "3":
            # Stop charging
            if self.state == "SUPPLYING" and self.current_session:
                driver_id = self.current_driver
                session = self.current_session
                
                elapsed = time.time() - session["start_time"]
                total_seconds = 14.0
                kwh_delivered = min(session["kwh_needed"], (elapsed / total_seconds) * session["kwh_needed"])
                total_amount = round(kwh_delivered * self.price_per_kwh, 2)
                
                end_msg = Protocol.encode(
                    Protocol.build_message("SUPPLY_END", self.cp_id, driver_id,
                                         kwh_delivered, total_amount)
                )
                
                try:
                    self.central_socket.send(end_msg)
                    output = f"{self.format_output('🔌 Vehicle unplugged', 'green')}\n"
                    output += f"{self.format_output(f'   {kwh_delivered:.3f} kWh, {total_amount:.2f}€', 'white')}\n"
                    await self.broadcast(output)
                    
                    self.state = "ACTIVATED"
                    self.current_driver = None
                    self.current_session = None
                    self.charging_complete = False
                except Exception as e:
                    await self.broadcast(self.format_output(f'❌ Error: {e}', 'red'))
            else:
                await self.broadcast(self.format_output('❌ Not currently charging', 'red'))
            
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
    
    async def handle_driver_id(self, driver_id):
        await self.broadcast(self.format_output('Enter kWh needed (default 10):', 'cyan'))
        return "WAIT_KWH", driver_id
    
    async def handle_kwh(self, kwh_str, driver_id):
        from shared.protocol import Protocol, MessageTypes
        
        try:
            kwh = float(kwh_str) if kwh_str else 10
            
            request_msg = Protocol.encode(
                Protocol.build_message(MessageTypes.REQUEST_CHARGE, driver_id, self.cp_id, kwh)
            )
            
            self.central_socket.send(request_msg)
            
            output = f"\n{self.format_output('📤 Sent charge request to CENTRAL', 'blue')}\n"
            output += f"{self.format_output(f'   Driver: {driver_id}', 'white')}\n"
            output += f"{self.format_output(f'   kWh: {kwh}', 'white')}\n"
            await self.broadcast(output)
        except ValueError:
            await self.broadcast(self.format_output('❌ Invalid kWh value', 'red'))
        
        return "MENU"
    
    def get_welcome_text(self):
        return f"""{self.format_output('╔══════════════════════════════════════════════════════════════╗', 'purple')}
{self.format_output('║', 'purple')}  {self.format_output(f'⚡ CP ENGINE - {self.cp_id}', 'cyan')}                                     {self.format_output('║', 'purple')}
{self.format_output('╚══════════════════════════════════════════════════════════════╝', 'purple')}

{self.format_output('Available Commands:', 'yellow')}
  {self.format_output('1.', 'cyan')} Request charge for driver
  {self.format_output('2.', 'cyan')} View status
  {self.format_output('3.', 'cyan')} Stop charging (unplug)
  {self.format_output('help', 'cyan')} - Show this help
  {self.format_output('clear', 'cyan')} - Clear terminal

{self.format_output(f'Location: ({self.latitude}, {self.longitude})', 'white')}
{self.format_output(f'Price: {self.price_per_kwh}€/kWh', 'white')}
{self.format_output('────────────────────────────────────────────────────────────', 'purple')}
"""
    
    def get_help_text(self):
        return self.get_welcome_text()
    
    async def handle_client(self, websocket):
        self.websocket_clients.add(websocket)
        await websocket.send(self.get_welcome_text())
        
        state = "MENU"
        temp_data = {}
        
        try:
            async for message in websocket:
                command = message.strip()
                if not command:
                    continue
                
                await websocket.send(f"$ {command}")
                
                if state == "MENU":
                    result = await self.handle_command(command)
                    if isinstance(result, tuple):
                        state = result[0]
                        temp_data['driver_id'] = result[1]
                    else:
                        state = result
                
                elif state == "WAIT_DRIVER_ID":
                    result = await self.handle_driver_id(command)
                    state = result[0]
                    temp_data['driver_id'] = result[1]
                
                elif state == "WAIT_KWH":
                    state = await self.handle_kwh(command, temp_data.get('driver_id'))
        
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.websocket_clients.remove(websocket)
    
    async def start_websocket_server(self):
        print(f"[{self.cp_id} Engine] Starting WebSocket server on port {self.ws_port}...")
        async with websockets.serve(self.handle_client, "0.0.0.0", self.ws_port):
            await asyncio.Future()

def main():
    if len(sys.argv) < 2:
        print("Usage: python engine_websocket.py <CP_ID> [lat] [lon] [price] [central_host] [central_port] [ws_port]")
        sys.exit(1)
    
    cp_id = sys.argv[1]
    latitude = sys.argv[2] if len(sys.argv) > 2 else "40.5"
    longitude = sys.argv[3] if len(sys.argv) > 3 else "-3.1"
    price = sys.argv[4] if len(sys.argv) > 4 else "0.30"
    central_host = sys.argv[5] if len(sys.argv) > 5 else "central"
    central_port = int(sys.argv[6]) if len(sys.argv) > 6 else 5000
    ws_port = int(sys.argv[7]) if len(sys.argv) > 7 else 9100
    
    server = EngineWebSocketServer(cp_id, latitude, longitude, price, central_host, central_port, ws_port)
    
    if not server.connect_to_central():
        print(f"[{cp_id}] Failed to connect to Central")
        sys.exit(1)
    
    print(f"[{cp_id} Engine] WebSocket URL: ws://localhost:{ws_port}")
    asyncio.run(server.start_websocket_server())

if __name__ == "__main__":
    main()