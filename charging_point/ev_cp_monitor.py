# ============================================================================
# EVCharging System - EV_CP_M (Charging Point Monitor) - FANCY UI
# ============================================================================

import socket
import threading
import time
import sys
import os
import requests  # ADD THIS if not already there
from config import CP_BASE_PORT, HEALTH_CHECK_INTERVAL
from shared.protocol import Protocol, MessageTypes
from datetime import datetime


class EVCPMonitor:
    def __init__(self, cp_id, engine_host="localhost", engine_port=None,
                 central_host="localhost", central_port=5000):
        self.cp_id = cp_id
        self.engine_host = engine_host
        self.engine_port = engine_port or (CP_BASE_PORT + int(cp_id.split('-')[1]))
        self.central_host = central_host
        self.central_port = central_port

        # ADD THESE LINES:
        self.registry_url = "http://registry:5001"  # Registry URL
        self.cp_username = None
        self.cp_password = None
        self.encryption_key = None

        self.engine_socket = None
        self.central_socket = None
        self.running = True
        self.lock = threading.Lock()

        # Status tracking
        self.engine_healthy = True
        self.consecutive_failures = 0
        self.failure_threshold = 3

        # Driver tracking
        self.current_driver = None
        self.charging_active = False
        self.charge_start_time = None
        self.charge_kwh_needed = 0
        self.charge_progress = 0
        self.last_progress_update = 0
        self.charging_complete = False

        print(f"[{self.cp_id} Monitor] Initializing...")
        print(f"[{self.cp_id} Monitor] Central: {self.central_host}:{self.central_port}")
        print(f"[{self.cp_id} Monitor] Engine: {self.engine_host}:{self.engine_port}")

    def _fetch_credentials_from_registry(self):
        """
        Fetch credentials from Registry for this CP
        Returns: dict with username and password, or None if failed
        """
        print(f"[{self.cp_id} Monitor] 🔑 Fetching credentials from Registry...")
        
        try:
            # Check if CP is registered
            response = requests.get(f"{self.registry_url}/list", timeout=10)
            
            if response.status_code != 200:
                print(f"[{self.cp_id} Monitor] ❌ Registry not responding")
                return None
            
            data = response.json()
            cps = data.get("charging_points", [])
            
            # Find this CP in the list
            for cp in cps:
                if cp['cp_id'] == self.cp_id:
                    # Found! But Registry doesn't return password
                    # We need to register to get credentials
                    print(f"[{self.cp_id} Monitor] ℹ️  CP already registered, using existing credentials")
                    
                    # In real system, credentials would be stored locally
                    # For now, we need to re-register to get password
                    # This is a simplification for the lab
                    
                    # Option 1: Register again (will fail if exists)
                    # Option 2: Store credentials locally after first registration
                    
                    # For this demo, let's assume CP was created via CP Manager
                    # which means Registry has credentials
                    # We'll need to modify this...
                    
                    print(f"[{self.cp_id} Monitor] ⚠️  Credentials should be stored locally")
                    print(f"[{self.cp_id} Monitor] ⚠️  For lab: Re-registering to get password")
                    
                    # Break and try to register
                    break
            
            # Register with Registry to get credentials
            # (In production, this would only happen once and credentials stored)
            lat = "40.5"  # Default values
            lon = "-3.1"
            price = 0.30
            
            # Try to extract from CP_ID if possible
            try:
                cp_num = int(self.cp_id.split('-')[1])
                lat = str(40.5 + (cp_num * 0.1))
                lon = str(-3.1 - (cp_num * 0.1))
            except:
                pass
            
            register_response = requests.post(
                f"{self.registry_url}/register",
                json={
                    "cp_id": self.cp_id,
                    "latitude": lat,
                    "longitude": lon,
                    "price_per_kwh": price
                },
                timeout=10
            )
            
            if register_response.status_code == 201:
                # New registration successful
                reg_data = register_response.json()
                credentials = {
                    "username": reg_data['username'],
                    "password": reg_data['password']
                }
                print(f"[{self.cp_id} Monitor] ✅ Got credentials from Registry")
                print(f"[{self.cp_id} Monitor]    Username: {credentials['username']}")
                return credentials
            
            elif register_response.status_code == 409:
                # Already registered - this is expected
                print(f"[{self.cp_id} Monitor] ℹ️  CP already in Registry")
                
                # PROBLEM: We can't get the password again!
                # Solution: For lab purposes, we'll use a workaround
                # In production: credentials would be stored in a config file
                
                print(f"[{self.cp_id} Monitor] ⚠️  LIMITATION: Cannot retrieve existing password")
                print(f"[{self.cp_id} Monitor] ⚠️  For lab: CPs should be created fresh each time")
                
                # For now, return None - CP must be created fresh
                return None
            
            else:
                print(f"[{self.cp_id} Monitor] ❌ Registry error: {register_response.status_code}")
                return None
        
        except Exception as e:
            print(f"[{self.cp_id} Monitor] ❌ Error fetching credentials: {e}")
            return None

    def connect_to_engine(self):
        """Connect to CP Engine"""
        print(f"[{self.cp_id} Monitor] Connecting to Engine at {self.engine_host}:{self.engine_port}...")
        
        max_retries = 10
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                self.engine_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.engine_socket.connect((self.engine_host, self.engine_port))
                print(f"[{self.cp_id} Monitor] ✅ Connected to Engine")
                return True
            except Exception as e:
                print(f"[{self.cp_id} Monitor] Attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    print(f"[{self.cp_id} Monitor] Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print(f"[{self.cp_id} Monitor] ❌ Failed to connect to Engine after {max_retries} attempts")
                    return False

    def connect_to_central(self):
        """Connect to CENTRAL and authenticate"""
        print(f"[{self.cp_id} Monitor] 🔌 Connecting to CENTRAL at {self.central_host}:{self.central_port}...")
        
        # Step 1: Fetch credentials from Registry
        credentials = self._fetch_credentials_from_registry()
        
        if not credentials:
            print(f"[{self.cp_id} Monitor] ❌ Failed to get credentials from Registry")
            print(f"[{self.cp_id} Monitor] ❌ Cannot authenticate without credentials")
            return False
        
        self.cp_username = credentials['username']
        self.cp_password = credentials['password']
        
        print(f"[{self.cp_id} Monitor] ✅ Credentials obtained")
        
        # Step 2: Connect to Central
        max_retries = 10
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                self.central_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.central_socket.connect((self.central_host, self.central_port))
                
                print(f"[{self.cp_id} Monitor] ✅ Socket connected to CENTRAL")
                break
            except Exception as e:
                print(f"[{self.cp_id} Monitor] Attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    print(f"[{self.cp_id} Monitor] ❌ Failed to connect after {max_retries} attempts")
                    return False
        
        # Step 3: Send AUTHENTICATE message instead of REGISTER
        print(f"[{self.cp_id} Monitor] 🔐 Authenticating with Central...")
        
        auth_msg = Protocol.encode(
            Protocol.build_message(
                MessageTypes.AUTHENTICATE,
                self.cp_id,
                self.cp_username,
                self.cp_password
            )
        )
        
        try:
            self.central_socket.send(auth_msg)
            print(f"[{self.cp_id} Monitor] 📤 AUTHENTICATE message sent")
        except Exception as e:
            print(f"[{self.cp_id} Monitor] ❌ Failed to send AUTHENTICATE: {e}")
            return False
        
        # Step 4: Wait for AUTHENTICATED or DENIED response
        print(f"[{self.cp_id} Monitor] ⏳ Waiting for authentication response...")
        
        try:
            self.central_socket.settimeout(10)  # 10 second timeout
            response_data = self.central_socket.recv(4096)
            self.central_socket.settimeout(None)  # Remove timeout
            
            if not response_data:
                print(f"[{self.cp_id} Monitor] ❌ No response from Central")
                return False
            
            # Decode response
            response_msg, is_valid = Protocol.decode(response_data)
            
            if not is_valid:
                print(f"[{self.cp_id} Monitor] ❌ Invalid response from Central")
                return False
            
            fields = Protocol.parse_message(response_msg)
            msg_type = fields[0]
            
            if msg_type == MessageTypes.AUTHENTICATED:
                # Success!
                if len(fields) > 2:
                    self.encryption_key = fields[2]
                    print(f"[{self.cp_id} Monitor] ✅ AUTHENTICATED! Encryption key received")
                    print(f"[{self.cp_id} Monitor] 🔑 Key: {self.encryption_key[:20]}...")
                else:
                    print(f"[{self.cp_id} Monitor] ✅ AUTHENTICATED!")
                
                # Register as monitor with CENTRAL (separate registration)
                register_msg = Protocol.encode(
                    Protocol.build_message(MessageTypes.REGISTER, "MONITOR", self.cp_id, self.cp_id)
                )
                self.central_socket.send(register_msg)
                
                print(f"[{self.cp_id} Monitor] ✅ Ready for operation")
                return True
            
            elif msg_type == MessageTypes.DENY:
                reason = fields[2] if len(fields) > 2 else "UNKNOWN"
                print(f"[{self.cp_id} Monitor] ❌ AUTHENTICATION DENIED: {reason}")
                return False
            
            else:
                print(f"[{self.cp_id} Monitor] ❌ Unexpected response: {msg_type}")
                return False
        
        except socket.timeout:
            print(f"[{self.cp_id} Monitor] ❌ Authentication timeout")
            return False
        except Exception as e:
            print(f"[{self.cp_id} Monitor] ❌ Authentication error: {e}")
            return False

    def _listen_central(self):
        """Listen for driver notifications from CENTRAL"""
        buffer = b''
        try:
            while self.running:
                try:
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

                            # Handle driver start notification
                            if msg_type == "DRIVER_START":
                                driver_id = fields[2]
                                with self.lock:
                                    self.current_driver = driver_id
                                    self.charging_active = True
                                    self.charge_start_time = datetime.now()
                                    self.charge_kwh_needed = 10
                                    self.charge_progress = 0
                                    self.last_progress_update = 0
                                    self.charging_complete = False
                                
                                print(f"\n╔{'═'*68}╗")
                                print(f"║{' '*68}║")
                                print(f"║  🚗  DRIVER CONNECTED - CHARGING SESSION STARTED  {'⚡':<22}║")
                                print(f"║{' '*68}║")
                                print(f"╠{'═'*68}╣")
                                print(f"║  📅 Start Time: {self.charge_start_time.strftime('%H:%M:%S'):<50}║")
                                print(f"║  ⏱️  Estimated Duration: ~14 seconds{' '*32}║")
                                print(f"║  🔋 Target: 100%{' '*52}║")
                                print(f"╚{'═'*68}╝\n")
                                
                                # Start progress monitoring thread
                                progress_thread = threading.Thread(
                                    target=self._monitor_progress,
                                    daemon=True
                                )
                                progress_thread.start()

                            # Handle charging complete notification
                            elif msg_type == "CHARGING_COMPLETE":
                                with self.lock:
                                    self.charging_complete = True
                                    self.charge_progress = 100
                                
                                print(f"\n╔{'═'*68}╗")
                                print(f"║{' '*68}║")
                                print(f"║  🎉  CHARGING COMPLETE - 100% REACHED!  {'🔋':<26}║")
                                print(f"║{' '*68}║")
                                print(f"╚{'═'*68}╝\n")

                            # Handle driver stop notification (unplugged)
                            elif msg_type == "DRIVER_STOP":
                                with self.lock:
                                    was_charging = self.charging_active or self.charging_complete
                                    final_progress = self.charge_progress
                                    self.current_driver = None
                                    self.charging_active = False
                                    self.charging_complete = False
                                    self.charge_progress = 0
                                
                                if was_charging:
                                    if final_progress >= 100:
                                        # Full charge completed
                                        print(f"\n╔{'═'*68}╗")
                                        print(f"║{' '*68}║")
                                        print(f"║  ✅  VEHICLE UNPLUGGED - SESSION COMPLETE  {'🔌':<24}║")
                                        print(f"║{' '*68}║")
                                        print(f"╠{'═'*68}╣")
                                        print(f"║  🔋 Final Charge: 100%{' '*44}║")
                                        print(f"║  💚 Battery: Full{' '*50}║")
                                        print(f"║  🎫 Ticket: Sent{' '*50}║")
                                        print(f"╚{'═'*68}╝\n")
                                    else:
                                        # Early disconnect
                                        print(f"\n╔{'═'*68}╗")
                                        print(f"║{' '*68}║")
                                        print(f"║  ⚠️   VEHICLE UNPLUGGED - EARLY DISCONNECT  {'🔌':<22}║")
                                        print(f"║{' '*68}║")
                                        print(f"╠{'═'*68}╣")
                                        print(f"║  🔋 Final Charge: {final_progress}%{' '*(45 - len(str(final_progress)))}║")
                                        print(f"║  ⚡ Status: Partial charge{' '*42}║")
                                        print(f"║  🎫 Ticket: Sent{' '*50}║")
                                        print(f"╚{'═'*68}╝\n")

                        else:
                            break

                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"[{self.cp_id} Monitor] Listener error: {e}")
                    break

        except Exception as e:
            print(f"[{self.cp_id} Monitor] CENTRAL connection lost: {e}")

    def _monitor_progress(self):
        """Monitor and display charging progress"""
        while self.running:
            # Check status
            with self.lock:
                should_stop = not self.charging_active and not self.charging_complete
                is_complete = self.charging_complete
                is_active = self.charging_active
                start_time = self.charge_start_time
            
            # Exit if no longer charging and not complete
            if should_stop:
                break
            
            # If charging complete, spam message every 2 seconds
            if is_complete:
                print(f"🔋 ⚡ 100% CHARGED - Please unplug vehicle to complete session ⚡ 🔋")
                time.sleep(2)
                continue
            
            # Calculate elapsed time
            if is_active and start_time:
                elapsed = (datetime.now() - start_time).total_seconds()
                
                # Calculate progress (14 seconds = 100%)
                progress = min(int((elapsed / 14.0) * 100), 100)
                
                # Only print every 2 seconds (approximately)
                with self.lock:
                    if progress >= self.last_progress_update + 14:  # 14% every 2 seconds
                        self.last_progress_update = progress
                        self.charge_progress = progress
                        
                        # Create progress bar with percentage
                        bar_length = 40
                        filled = int(bar_length * progress / 100)
                        bar = '█' * filled + '░' * (bar_length - filled)
                        
                        # Time remaining
                        time_remaining = max(0, 14 - int(elapsed))
                        
                        print(f"⚡ [{bar}] {progress}% | ⏱️  {time_remaining}s remaining")
                        
                        if progress >= 100:
                            self.charging_complete = True
            
            time.sleep(2)

    def health_check_loop(self):
        """Send health checks to engine every second"""
        while self.running:
            time.sleep(HEALTH_CHECK_INTERVAL)

            try:
                if not self.engine_socket:
                    continue

                # Send health check
                health_msg = Protocol.encode(
                    Protocol.build_message(MessageTypes.HEALTH_CHECK, self.cp_id)
                )
                self.engine_socket.send(health_msg)

                # Wait for response with timeout
                self.engine_socket.settimeout(2)
                try:
                    response_data = self.engine_socket.recv(4096)

                    if response_data:
                        response, is_valid = Protocol.decode(response_data)

                        if is_valid:
                            fields = Protocol.parse_message(response)

                            if fields[0] == "HEALTH_OK":
                                with self.lock:
                                    if not self.engine_healthy:
                                        print(f"\n╔{'═'*68}╗")
                                        print(f"║{' '*68}║")
                                        print(f"║  ✅  ENGINE RECOVERED - System operational  {'💚':<24}║")
                                        print(f"║{' '*68}║")
                                        print(f"╚{'═'*68}╝\n")
                                        
                                        # Send recovery to CENTRAL
                                        recovery_msg = Protocol.encode(
                                            Protocol.build_message(
                                                MessageTypes.RECOVERY, self.cp_id
                                            )
                                        )
                                        self.central_socket.send(recovery_msg)

                                    self.engine_healthy = True
                                    self.consecutive_failures = 0

                            elif fields[0] == "HEALTH_KO":
                                self._handle_engine_fault()

                        else:
                            self._handle_engine_fault()
                    else:
                        self._handle_engine_fault()

                except socket.timeout:
                    self._handle_engine_fault()

            except Exception as e:
                print(f"[{self.cp_id} Monitor] Health check error: {e}")
                self._handle_engine_fault()

    def _handle_engine_fault(self):
        """Handle engine fault detection"""
        with self.lock:
            self.consecutive_failures += 1

            if self.consecutive_failures >= self.failure_threshold:
                if self.engine_healthy:
                    self.engine_healthy = False
                    print(f"\n╔{'═'*68}╗")
                    print(f"║{' '*68}║")
                    print(f"║  ⚠️   ENGINE FAULT DETECTED - Critical failure!  {'🔴':<18}║")
                    print(f"║{' '*68}║")
                    print(f"╠{'═'*68}╣")
                    print(f"║  🔧 Status: Not responding to health checks{' '*23}║")
                    print(f"║  📡 Action: Notifying central system...{' '*27}║")
                    print(f"║  ⏳ Recovery: Monitoring for reconnection{' '*24}║")
                    print(f"╚{'═'*68}╝\n")

                    # Send fault to CENTRAL
                    try:
                        fault_msg = Protocol.encode(
                            Protocol.build_message(MessageTypes.FAULT, self.cp_id)
                        )
                        self.central_socket.send(fault_msg)
                    except Exception as e:
                        print(f"[{self.cp_id} Monitor] Failed to send fault: {e}")

    def display_menu(self):
        """Display interactive menu"""
        print(f"\n╔{'═'*68}╗")
        print(f"║{' '*68}║")
        print(f"║  {self.cp_id} MONITOR - Ready for operation  {'🖥️':<28}║")
        print(f"║{' '*68}║")
        print(f"╚{'═'*68}╝\n")
        
        while self.running:
            try:
                cmd = input(f"\n[{self.cp_id} Monitor]> ").strip().lower()

                if cmd == "help":
                    print(f"\n╔{'═'*68}╗")
                    print(f"║  {self.cp_id} MONITOR COMMANDS{' '*40}║")
                    print(f"╠{'═'*68}╣")
                    print(f"║  status  - View current status and health{' '*26}║")
                    print(f"║  help    - Show this help menu{' '*37}║")
                    print(f"║  quit    - Exit monitor{' '*44}║")
                    print(f"╚{'═'*68}╝\n")

                elif cmd == "status":
                    with self.lock:
                        engine_icon = "💚" if self.engine_healthy else "🔴"
                        engine_text = "HEALTHY" if self.engine_healthy else "FAULTY"
                        
                        if self.charging_complete:
                            status_text = "CHARGED TO 100% - WAITING FOR UNPLUG"
                            status_icon = "🔋"
                        elif self.charging_active:
                            status_text = "CHARGING IN PROGRESS"
                            status_icon = "⚡"
                        else:
                            status_text = "AVAILABLE"
                            status_icon = "🟢"
                        
                        print(f"\n╔{'═'*68}╗")
                        print(f"║  {self.cp_id} STATUS REPORT{' '*42}║")
                        print(f"╠{'═'*68}╣")
                        print(f"║  Engine Status: {engine_text} {engine_icon}{' '*(43 - len(engine_text))}║")
                        print(f"║  Health Checks: {self.consecutive_failures}/{self.failure_threshold} failures{' '*37}║")
                        print(f"║  Point Status: {status_text} {status_icon}{' '*(43 - len(status_text))}║")
                        
                        if self.charging_active or self.charging_complete:
                            if self.charge_start_time:
                                elapsed = (datetime.now() - self.charge_start_time).total_seconds()
                                print(f"╠{'═'*68}╣")
                                print(f"║  Time Elapsed: {int(elapsed)}s{' '*(51 - len(str(int(elapsed))))}║")
                                print(f"║  Progress: {self.charge_progress}%{' '*(55 - len(str(self.charge_progress)))}║")
                        
                        print(f"╚{'═'*68}╝\n")

                elif cmd == "quit":
                    print(f"\n╔{'═'*68}╗")
                    print(f"║{' '*68}║")
                    print(f"║  {self.cp_id} Monitor shutting down...  {'👋':<32}║")
                    print(f"║{' '*68}║")
                    print(f"╚{'═'*68}╝\n")
                    self.running = False
                    break

                elif cmd == "":
                    continue

                else:
                    print(f"\n❌ Unknown command: '{cmd}'. Type 'help' for available commands.\n")

            except EOFError:
                break
            except KeyboardInterrupt:
                print(f"\n\n╔{'═'*68}╗")
                print(f"║{' '*68}║")
                print(f"║  {self.cp_id} Monitor interrupted  {'⚠️':<36}║")
                print(f"║{' '*68}║")
                print(f"╚{'═'*68}╝\n")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}\n")

    def run(self):
        """Run the monitor"""
        print(f"[{self.cp_id} Monitor] Starting...")

        if not self.connect_to_engine():
            print(f"[{self.cp_id} Monitor] Cannot connect to Engine")
            return

        if not self.connect_to_central():
            print(f"[{self.cp_id} Monitor] Cannot connect to CENTRAL")
            return

        # Start CENTRAL listener
        central_thread = threading.Thread(
            target=self._listen_central,
            daemon=True
        )
        central_thread.start()

        # Start health check loop in background
        health_thread = threading.Thread(
            target=self.health_check_loop,
            daemon=True
        )
        health_thread.start()

        # Display menu
        try:
            self.display_menu()
        except KeyboardInterrupt:
            print(f"\n[{self.cp_id} Monitor] Shutting down...")
        finally:
            self.running = False
            if self.engine_socket:
                self.engine_socket.close()
            if self.central_socket:
                self.central_socket.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ev_cp_monitor.py <CP_ID> [engine_host] [engine_port] "
              "[central_host] [central_port]")
        sys.exit(1)

    cp_id = sys.argv[1]
    engine_host = sys.argv[2] if len(sys.argv) > 2 else "localhost"
    engine_port = int(sys.argv[3]) if len(sys.argv) > 3 else None
    central_host = sys.argv[4] if len(sys.argv) > 4 else "localhost"
    central_port = int(sys.argv[5]) if len(sys.argv) > 5 else 5000

    monitor = EVCPMonitor(cp_id, engine_host, engine_port, central_host, central_port)
    monitor.run()