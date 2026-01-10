#!/usr/bin/env python3
"""
EV_W (Weather Control Office) - FIXED VERSION
Dynamically monitors CPs from Central and checks weather conditions
"""

import requests
import time
from datetime import datetime

# ============================================================================
# CONFIGURATION
# ============================================================================

OPENWEATHER_API_KEY = "0dd2fb3fbe091298b89e507c2a7acae4"
CENTRAL_API_URL = "http://central:8080/api"
CHECK_INTERVAL = 10  # Check every 10 seconds to save API credits

# ============================================================================
# WEATHER SERVICE
# ============================================================================

class WeatherService:
    def __init__(self, api_key, central_url):
        self.api_key = api_key
        self.central_url = central_url
        self.current_alerts = {}  # Track active alerts per CP
        
        print("=" * 70)
        print("  EV_W (Weather Control Office) - STARTED")
        print("=" * 70)
        print(f"\nCentral API: {central_url}")
        print(f"Check Interval: {CHECK_INTERVAL} seconds")
        print(f"Alert Threshold: ≤ 0°C\n")
    
    def get_active_cps(self):
        """Fetch active CPs from Central"""
        try:
            response = requests.get(f"{self.central_url}/cps", timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                cps = data.get('charging_points', [])
                
                # Filter only ACTIVATED or SUPPLYING CPs
                active_cps = []
                for cp in cps:
                    if cp['state'] in ['ACTIVATED', 'SUPPLYING']:
                        active_cps.append({
                            'cp_id': cp['cp_id'],
                            'latitude': cp['location']['latitude'],
                            'longitude': cp['location']['longitude']
                        })
                
                return active_cps
            else:
                print(f"⚠️  Failed to fetch CPs: {response.status_code}")
                return []
        
        except Exception as e:
            print(f"❌ Error fetching CPs from Central: {e}")
            return []
    
    def get_temperature_by_coords(self, lat, lon):
        """
        Query OpenWeather API for current temperature using coordinates
        Returns: temperature in Celsius, or None if error
        """
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather"
            params = {
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": "metric"  # Celsius
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                temp = data['main']['temp']
                city = data.get('name', 'Unknown')
                return temp, city
            else:
                print(f"⚠️  Weather API error: {response.status_code}")
                return None, None
        
        except Exception as e:
            print(f"❌ Error fetching weather: {e}")
            return None, None
    
    def send_alert(self, cp_id, location, temperature):
        """Send cold weather alert to Central"""
        try:
            url = f"{self.central_url}/weather/alert"
            payload = {
                "cp_id": cp_id,
                "location": location,
                "temperature": temperature
            }
            
            response = requests.post(url, json=payload, timeout=5)
            
            if response.status_code == 200:
                print(f"🚨 ALERT: {cp_id} at {location} - {temperature}°C → DISABLED")
                self.current_alerts[cp_id] = True
                return True
            else:
                print(f"⚠️  Failed to send alert: {response.status_code}")
                return False
        
        except Exception as e:
            print(f"❌ Error sending alert: {e}")
            return False
    
    def send_clear(self, cp_id, location, temperature):
        """Send weather clear signal to Central"""
        try:
            url = f"{self.central_url}/weather/clear"
            payload = {
                "cp_id": cp_id,
                "location": location,
                "temperature": temperature
            }
            
            response = requests.post(url, json=payload, timeout=5)
            
            if response.status_code == 200:
                print(f"✅ CLEAR: {cp_id} at {location} - {temperature}°C → ENABLED")
                self.current_alerts[cp_id] = False
                return True
            else:
                print(f"⚠️  Failed to send clear: {response.status_code}")
                return False
        
        except Exception as e:
            print(f"❌ Error sending clear: {e}")
            return False
    
    def check_weather_loop(self):
        """Main loop - check weather periodically"""
        print("\n🌡️  Starting weather monitoring...\n")
        
        while True:
            try:
                timestamp = datetime.now().strftime('%H:%M:%S')
                print(f"[{timestamp}] Checking weather...")
                
                # Get active CPs from Central
                active_cps = self.get_active_cps()
                
                if not active_cps:
                    print("   ℹ️  No active CPs to monitor")
                    print()
                    time.sleep(CHECK_INTERVAL)
                    continue
                
                print(f"   📍 Monitoring {len(active_cps)} CP(s)")
                
                for cp in active_cps:
                    cp_id = cp['cp_id']
                    lat = cp['latitude']
                    lon = cp['longitude']
                    
                    # Get temperature
                    temp, city = self.get_temperature_by_coords(lat, lon)
                    
                    if temp is None:
                        continue
                    
                    # Round to 1 decimal
                    temp = round(temp, 1)
                    
                    # Check if alert is currently active
                    is_alerted = self.current_alerts.get(cp_id, False)
                    
                    if temp <= 0:
                        # Cold weather - send alert if not already alerted
                        if not is_alerted:
                            self.send_alert(cp_id, city, temp)
                        else:
                            print(f"   ❄️  {cp_id} at {city}: {temp}°C (already disabled)")
                    
                    else:
                        # Normal weather - send clear if currently alerted
                        if is_alerted:
                            self.send_clear(cp_id, city, temp)
                        else:
                            print(f"   ☀️  {cp_id} at {city}: {temp}°C (operational)")
                
                print()  # Blank line for readability
                time.sleep(CHECK_INTERVAL)
            
            except KeyboardInterrupt:
                print("\n\n👋 Weather monitoring stopped")
                break
            except Exception as e:
                print(f"❌ Error in monitoring loop: {e}")
                time.sleep(CHECK_INTERVAL)

# ============================================================================
# MAIN
# ============================================================================

def main():
    # Create service
    service = WeatherService(
        api_key=OPENWEATHER_API_KEY,
        central_url=CENTRAL_API_URL
    )
    
    # Start monitoring
    service.check_weather_loop()

if __name__ == "__main__":
    main()