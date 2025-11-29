"""
BME680 Weather Monitoring Firmware for ESP32
Based on working sensor code with WiFi and API integration
"""

from machine import Pin, I2C
import bme680
import time
import json
import network
import urequests as requests

# ============================================================================
# CONFIGURATION
# ============================================================================

# I2C Configuration
I2C_SCL_PIN = 22
I2C_SDA_PIN = 21
I2C_FREQ = 100000
BME680_ADDRESS = 0x76  # Change to 0x77 if your sensor uses that address

# Backend server configuration (can be overridden in wifi.json)
BACKEND_URL = None  # Will be loaded from wifi.json
BACKEND_TIMEOUT = 10  # seconds

# Data collection interval (in seconds)
DATA_INTERVAL = 300  # 5 minutes

# WiFi connection timeout
WIFI_TIMEOUT = 30  # seconds

# ============================================================================
# FUNCTIONS
# ============================================================================

def load_wifi_config():
    """Load WiFi credentials and backend URL from wifi.json file."""
    try:
        with open('wifi.json', 'r') as f:
            config = json.load(f)
            # Validate required fields
            if 'ssid' not in config or 'password' not in config:
                raise ValueError("wifi.json must contain 'ssid' and 'password' fields")
            # Backend URL is optional, can be set in config or use default
            if 'backend_url' not in config:
                raise ValueError("wifi.json must contain 'backend_url' field. Example: 'http://your-server-ip:8811/temprec'")
            return config
    except Exception as e:
        print(f"Error loading WiFi config: {e}")
        raise

def connect_wifi(ssid, password):
    """Connect to WiFi network."""
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    wifi.connect(ssid, password)
    
    print(f"Connecting to WiFi '{ssid}'...")
    start_time = time.time()
    
    while not wifi.isconnected():
        if time.time() - start_time > WIFI_TIMEOUT:
            raise RuntimeError("WiFi connection timeout")
        time.sleep(0.5)
        print('.', end='')
    
    print("\nWiFi connected!")
    print(f"  IP Address: {wifi.ifconfig()[0]}")
    return wifi

def calculate_aqi(gas_resistance):
    """
    Convert BME680 gas resistance to Air Quality Index (AQI).
    
    AQI Scale:
    - 0-50: Good
    - 51-100: Moderate
    - 101-150: Unhealthy for Sensitive Groups
    - 151-200: Unhealthy
    - 201-300: Very Unhealthy
    - 301-500: Hazardous
    """
    if gas_resistance <= 0:
        return 500
    
    # Lower resistance = worse air quality = higher AQI
    if gas_resistance >= 500000:
        # Excellent air quality
        aqi = max(0, int(25 * (1 - min(1, (gas_resistance - 500000) / 500000))))
    elif gas_resistance >= 200000:
        # Good air quality
        aqi = 50 + int((200000 - gas_resistance) / 300000 * 50)
    elif gas_resistance >= 100000:
        # Moderate
        aqi = 100 + int((100000 - gas_resistance) / 100000 * 50)
    elif gas_resistance >= 50000:
        # Unhealthy for sensitive
        aqi = 150 + int((50000 - gas_resistance) / 50000 * 50)
    elif gas_resistance >= 25000:
        # Unhealthy
        aqi = 200 + int((25000 - gas_resistance) / 25000 * 100)
    else:
        # Very unhealthy to hazardous
        aqi = 300 + int((25000 - gas_resistance) / 25000 * 200)
    
    # Clamp AQI to 0-500 range
    return max(0, min(500, aqi))

def send_data(url, data):
    """Send data to backend server."""
    try:
        response = requests.post(
            url,
            json=data,
            headers={'Content-Type': 'application/json'},
            timeout=BACKEND_TIMEOUT
        )
        
        if response.status_code == 200:
            print(f"Data sent successfully: {response.text}")
            response.close()
            return True
        else:
            print(f"Server error: {response.status_code} - {response.text}")
            response.close()
            return False
            
    except Exception as e:
        print(f"Error sending data: {e}")
        return False

# ============================================================================
# MAIN PROGRAM
# ============================================================================

def main():
    print("\n" + "="*50)
    print("BME680 Weather Monitoring System")
    print("="*50)
    
    # Initialize I2C
    print(f"\nInitializing I2C (SCL=GPIO{I2C_SCL_PIN}, SDA=GPIO{I2C_SDA_PIN})...")
    i2c = I2C(0, scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN), freq=I2C_FREQ)
    
    # Scan for devices
    devices = i2c.scan()
    print(f"Found I2C devices: {[hex(d) for d in devices]}")
    
    # Initialize sensor
    print(f"\nInitializing BME680 at address 0x{BME680_ADDRESS:02X}...")
    sensor = bme680.BME680_I2C(i2c, address=BME680_ADDRESS)
    print("Sensor initialized successfully!")
    
    # Load WiFi config
    print("\nLoading WiFi configuration...")
    wifi_config = load_wifi_config()
    
    # Get backend URL from config
    global BACKEND_URL
    BACKEND_URL = wifi_config.get('backend_url')
    if not BACKEND_URL:
        raise ValueError("backend_url must be specified in wifi.json")
    print(f"Backend URL: {BACKEND_URL}")
    
    # Connect to WiFi
    wifi = connect_wifi(wifi_config['ssid'], wifi_config['password'])
    
    # Main loop
    print("\n" + "="*50)
    print("Starting data collection loop...")
    print(f"Data interval: {DATA_INTERVAL} seconds ({DATA_INTERVAL/60:.1f} minutes)")
    print("="*50 + "\n")
    
    cycle = 0
    
    while True:
        cycle += 1
        print(f"\n--- Cycle {cycle} ---")
        print(f"Time: {time.localtime()}")
        
        try:
            # Check WiFi connection
            if not wifi.isconnected():
                print("WiFi disconnected. Reconnecting...")
                wifi = connect_wifi(wifi_config['ssid'], wifi_config['password'])
            
            # Read sensor data
            print("Reading sensor...")
            temp = sensor.temperature
            pres = sensor.pressure
            hum = sensor.humidity
            gas = sensor.gas
            
            print(f"  Temperature: {temp}°C")
            print(f"  Pressure: {pres}hPa")
            print(f"  Humidity: {hum}%")
            print(f"  Gas resistance: {gas}Ω")
            
            # Calculate AQI
            aqi = calculate_aqi(gas)
            print(f"  AQI: {aqi}")
            
            # Prepare data for API
            data = {
                "temperature": round(temp, 2),
                "humidity": round(hum, 2),
                "pressure": round(pres, 2),
                "gas_resistance": int(gas),
                "aqi": aqi
            }
            
            # Send to server
            print("\nSending data to server...")
            if send_data(BACKEND_URL, data):
                print("✓ Success!")
            else:
                print("✗ Failed to send data")
            
        except Exception as e:
            print(f"Error in main loop: {e}")
            import sys
            sys.print_exception(e)
        
        # Wait for next reading
        print(f"\nWaiting {DATA_INTERVAL} seconds until next reading...")
        time.sleep(DATA_INTERVAL)

if __name__ == "__main__":
    main()
