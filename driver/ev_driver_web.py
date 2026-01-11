#!/usr/bin/env python3
"""
Driver Terminal Bridge - WebSocket to Docker stdin/stdout
Provides real terminal access to Driver containers via WebSocket
"""

import asyncio
import websockets
import docker
import sys
from threading import Thread
import signal

PORT = 8085

class DriverTerminalBridge:
    def __init__(self):
        self.docker_client = docker.from_env()
        self.active_connections = {}
        
    async def handle_client(self, websocket, path):
        """Handle WebSocket connection from browser"""
        # Parse driver number from path (e.g., /1 for driver_1, /auto for driver_auto)
        try:
            driver_id = path.strip('/') or '1'
            
            if driver_id.lower() == 'auto':
                container_name = "evcharging_driver_auto"
            else:
                container_name = f"evcharging_driver_{driver_id}"
        except:
            await websocket.send("Error: Invalid driver ID")
            return
        
        print(f"[Driver Bridge] Connection for {container_name}")
        
        try:
            # Get container
            container = self.docker_client.containers.get(container_name)
            
            # Send welcome message
            await websocket.send(f"\033[92m✓ Connected to {container_name}\033[0m\n")
            await websocket.send(f"\033[93mType commands for the Driver interactive menu\033[0m\n")
            await websocket.send("─" * 60 + "\n")
            
            # Attach to container with stdin/stdout
            sock = container.attach_socket(params={
                'stdin': 1,
                'stdout': 1,
                'stderr': 1,
                'stream': 1
            })
            
            # Store connection
            self.active_connections[websocket] = {
                'container': container,
                'socket': sock
            }
            
            # Create tasks for bidirectional communication
            read_task = asyncio.create_task(self.read_from_container(websocket, sock))
            write_task = asyncio.create_task(self.write_to_container(websocket, sock))
            
            # Wait for either task to complete (disconnect)
            done, pending = await asyncio.wait(
                [read_task, write_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                
        except docker.errors.NotFound:
            await websocket.send(f"\033[91m✗ Container {container_name} not found\033[0m\n")
            await websocket.send(f"\033[93mMake sure the Driver is running\033[0m\n")
        except Exception as e:
            await websocket.send(f"\033[91m✗ Error: {e}\033[0m\n")
        finally:
            # Cleanup
            if websocket in self.active_connections:
                sock = self.active_connections[websocket]['socket']
                try:
                    sock.close()
                except:
                    pass
                del self.active_connections[websocket]
            print(f"[Driver Bridge] Disconnected from {container_name}")
    
    async def read_from_container(self, websocket, sock):
        """Read output from container and send to WebSocket"""
        try:
            loop = asyncio.get_event_loop()
            while True:
                # Read from socket (blocking, so run in executor)
                data = await loop.run_in_executor(None, sock._sock.recv, 4096)
                if not data:
                    break
                
                # Decode and send to browser
                try:
                    text = data.decode('utf-8', errors='replace')
                    await websocket.send(text)
                except:
                    pass
        except Exception as e:
            print(f"[Driver Bridge] Read error: {e}")
    
    async def write_to_container(self, websocket, sock):
        """Read from WebSocket and write to container stdin"""
        try:
            async for message in websocket:
                # Add newline if not present
                if not message.endswith('\n'):
                    message += '\n'
                
                # Send to container
                sock._sock.send(message.encode('utf-8'))
        except Exception as e:
            print(f"[Driver Bridge] Write error: {e}")

async def main():
    bridge = DriverTerminalBridge()
    
    print("=" * 70)
    print("  Driver Terminal Bridge - STARTED")
    print("=" * 70)
    print(f"\n  WebSocket URL: ws://localhost:{PORT}/<driver_id>")
    print(f"  Examples:")
    print(f"    ws://localhost:{PORT}/1 for evcharging_driver_1")
    print(f"    ws://localhost:{PORT}/2 for evcharging_driver_2")
    print(f"    ws://localhost:{PORT}/auto for evcharging_driver_auto")
    print("  Waiting for browser connections...\n")
    
    async with websockets.serve(bridge.handle_client, "0.0.0.0", PORT):
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())