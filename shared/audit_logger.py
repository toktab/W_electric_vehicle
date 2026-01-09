# ============================================================================
# Audit Logger - Thread-safe logging for security events
# ============================================================================

import threading
import os
from datetime import datetime


class AuditLogger:
    def __init__(self, log_file="data/audit_log.txt"):
        self.log_file = log_file
        self.lock = threading.Lock()
        
        # Create data directory if doesn't exist
        os.makedirs("data", exist_ok=True)
        
        # Create file with header if doesn't exist
        if not os.path.exists(log_file):
            with open(log_file, 'w') as f:
                f.write("# EV Charging System - Audit Log\n")
                f.write("# Format: TIMESTAMP | IP_ADDRESS | ENTITY | EVENT_TYPE | PARAMETERS\n")
                f.write("#" + "="*100 + "\n")
    
    def log(self, entity, event_type, ip_address, parameters):
        """
        Log an event to the audit file
        
        Args:
            entity: Who (CP-001, DRIVER-001, ADMIN, etc.)
            event_type: What happened (AUTHENTICATION_SUCCESS, CHARGE_REQUESTED, etc.)
            ip_address: IP address of the entity
            parameters: Details (string or dict)
        """
        with self.lock:
            try:
                timestamp = datetime.now().isoformat()
                
                # Convert parameters to string if dict
                if isinstance(parameters, dict):
                    params_str = ", ".join([f"{k}={v}" for k, v in parameters.items()])
                else:
                    params_str = str(parameters)
                
                # Format: TIMESTAMP | IP | ENTITY | EVENT | PARAMS
                log_line = f"{timestamp} | {ip_address} | {entity} | {event_type} | {params_str}\n"
                
                with open(self.log_file, 'a') as f:
                    f.write(log_line)
                
            except Exception as e:
                print(f"[AuditLogger] Error writing log: {e}")
    
    def get_recent(self, lines=50):
        """Get recent log entries"""
        try:
            with open(self.log_file, 'r') as f:
                all_lines = f.readlines()
                return all_lines[-lines:]
        except Exception as e:
            print(f"[AuditLogger] Error reading log: {e}")
            return []