"""
BME680 Weather Monitoring Firmware for ESP32
Power-efficient version optimized for battery operation
Uses deep sleep mode to minimize power consumption
"""

from machine import Pin, I2C, deepsleep
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

# Power management configuration
USE_DEEP_SLEEP = True  # Set to False to disable deep sleep (for debugging) - deprecated, use onBattery in wifi.json
DATA_INTERVAL = None  # Will be loaded from wifi.json (default: 300 seconds = 5 minutes)
ON_BATTERY = None  # Will be loaded from wifi.json (default: False - keep running with delay)

# WiFi connection timeout
WIFI_TIMEOUT = 30  # seconds

# Power optimization settings
DISCONNECT_WIFI_AFTER_SEND = False  # Keep WiFi connected to ensure reliable data transmission

# ============================================================================
# FUNCTIONS
# ============================================================================

def load_wifi_config():
    """Load WiFi credentials, backend URL, port, and data interval from wifi.json file."""
    try:
        with open('wifi.json', 'r') as f:
            config = json.load(f)
            # Validate required fields
            if 'ssid' not in config or 'password' not in config:
                raise ValueError("wifi.json must contain 'ssid' and 'password' fields")
            if 'backend_url' not in config:
                raise ValueError("wifi.json must contain 'backend_url' field. Example: 'http://your-server-ip:8811/temprec'")
            
            # Validate and set port
            if 'port' in config:
                port = config['port']
                if not isinstance(port, int) or port < 1 or port > 65535:
                    raise ValueError("port must be an integer between 1 and 65535")
                config['port'] = port
                # Update backend_url with the specified port
                backend_url = config['backend_url']
                # Replace port in URL if it exists, or add it
                if '://' in backend_url:
                    # Parse and replace port in URL
                    parts = backend_url.split('://', 1)
                    if len(parts) == 2:
                        protocol = parts[0]
                        rest = parts[1]
                        # Split host:port from path
                        if '/' in rest:
                            host_port = rest.split('/', 1)[0]
                            path_part = '/' + rest.split('/', 1)[1]
                        else:
                            host_port = rest
                            path_part = ''
                        
                        # Extract host (remove port if present)
                        if ':' in host_port:
                            host = host_port.split(':')[0]
                        else:
                            host = host_port
                        
                        # Construct new URL with specified port
                        config['backend_url'] = f"{protocol}://{host}:{port}{path_part}"
            else:
                # Default port if not specified
                config['port'] = 8811
                print("Warning: port not specified in wifi.json, using default: 8811")
            
            # Validate data_interval if provided
            if 'data_interval' in config:
                interval = config['data_interval']
                if not isinstance(interval, int) or interval < 60:
                    raise ValueError("data_interval must be an integer >= 60 seconds (minimum 1 minute)")
                config['data_interval'] = interval
            else:
                # Default to 5 minutes if not specified
                config['data_interval'] = 300
                print("Warning: data_interval not specified in wifi.json, using default: 300 seconds (5 minutes)")
            
            # Validate onBattery if provided
            if 'onBattery' in config:
                on_battery = config['onBattery']
                if not isinstance(on_battery, bool):
                    raise ValueError("onBattery must be a boolean (true or false)")
                config['onBattery'] = on_battery
            else:
                # Default to False if not specified (keep running with delay)
                config['onBattery'] = False
                print("Warning: onBattery not specified in wifi.json, using default: false (keep running with delay)")
            
            return config
    except Exception as e:
        print(f"Error loading WiFi config: {e}")
        raise

def connect_wifi(ssid, password, max_retries=3):
    """Connect to WiFi network with retry logic."""
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    
    for attempt in range(max_retries):
        # Check if already connected
        if wifi.isconnected():
            print(f"WiFi already connected! IP: {wifi.ifconfig()[0]}")
            return wifi
        
        # Try to connect
        print(f"Connecting to WiFi '{ssid}' (attempt {attempt + 1}/{max_retries})...")
        wifi.connect(ssid, password)
        
        start_time = time.time()
        while not wifi.isconnected():
            if time.time() - start_time > WIFI_TIMEOUT:
                print(f"  Connection timeout (attempt {attempt + 1}/{max_retries})")
                break
            time.sleep(0.5)
            print('.', end='')
        
        if wifi.isconnected():
            print("\nWiFi connected!")
            print(f"  IP Address: {wifi.ifconfig()[0]}")
            return wifi
        else:
            print("\n  Connection failed, retrying...")
            time.sleep(2)  # Wait before retry
    
    raise RuntimeError(f"WiFi connection failed after {max_retries} attempts")

def ensure_wifi_connected(ssid, password):
    """Ensure WiFi is connected, reconnect if necessary."""
    wifi = network.WLAN(network.STA_IF)
    if not wifi.isconnected():
        print("WiFi disconnected, reconnecting...")
        return connect_wifi(ssid, password)
    return wifi

def disconnect_wifi():
    """Disconnect WiFi to save power."""
    wifi = network.WLAN(network.STA_IF)
    if wifi.isconnected():
        wifi.disconnect()
        wifi.active(False)
        print("WiFi disconnected to save power")

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

def send_data(url, data, wifi, ssid, password):
    """Send data to backend server with WiFi connection check."""
    # Ensure WiFi is still connected before sending
    wifi = ensure_wifi_connected(ssid, password)
    
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
        # Try to reconnect if connection was lost
        if not wifi.isconnected():
            print("WiFi lost during send, will reconnect on next cycle")
        return False

# ============================================================================
# MAIN PROGRAM
# ============================================================================

def main():
    print("\n" + "="*50)
    print("BME680 Weather Monitoring System")
    print("="*50)
    
    # Load WiFi config first (before initializing hardware)
    print("\nLoading WiFi configuration...")
    wifi_config = load_wifi_config()
    
    # Get backend URL and port from config
    global BACKEND_URL, DATA_INTERVAL, ON_BATTERY
    BACKEND_URL = wifi_config.get('backend_url')
    if not BACKEND_URL:
        raise ValueError("backend_url must be specified in wifi.json")
    port = wifi_config.get('port', 8811)
    print(f"Backend URL: {BACKEND_URL}")
    print(f"Port: {port}")
    
    # Get data interval from config
    DATA_INTERVAL = wifi_config.get('data_interval', 300)
    print(f"Data interval: {DATA_INTERVAL} seconds ({DATA_INTERVAL/60:.1f} minutes)")
    
    # Get onBattery setting from config
    ON_BATTERY = wifi_config.get('onBattery', False)
    if ON_BATTERY:
        print("Power mode: Battery (will use deep sleep)")
    else:
        print("Power mode: AC Power (will keep running with delay)")
    
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
    
    # Main loop - runs continuously if onBattery is False, or once if True (then deep sleep)
    while True:
        # Record start time to calculate actual sleep duration
        cycle_start_time = time.time()
        
        try:
            # Ensure WiFi is connected (will reconnect if needed)
            print("\nChecking WiFi connection...")
            wifi = ensure_wifi_connected(wifi_config['ssid'], wifi_config['password'])
            
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
            
            # Send to server (with WiFi connection check)
            print("\nSending data to server...")
            send_success = send_data(BACKEND_URL, data, wifi, wifi_config['ssid'], wifi_config['password'])
            if send_success:
                print("✓ Success!")
            else:
                print("✗ Failed to send data")
            
            # Only disconnect WiFi if explicitly configured to save power (not recommended)
            if DISCONNECT_WIFI_AFTER_SEND:
                disconnect_wifi()
            else:
                # Verify WiFi is still connected
                wifi = network.WLAN(network.STA_IF)
                if wifi.isconnected():
                    print("WiFi remains connected for next cycle")
                else:
                    print("Warning: WiFi disconnected, will reconnect on next cycle")
            
        except Exception as e:
            print(f"Error in main loop: {e}")
            import sys
            sys.print_exception(e)
        
        # Calculate time spent awake and adjust sleep duration
        time_awake = time.time() - cycle_start_time
        
        # Enter sleep mode based on onBattery setting
        if ON_BATTERY:
            # Battery mode: Use deep sleep to save power
            actual_sleep_ms = int((DATA_INTERVAL - time_awake) * 1000)
            
            # Ensure minimum sleep time (at least 1 second)
            if actual_sleep_ms < 1000:
                actual_sleep_ms = 1000
                print(f"\nWarning: Cycle took {time_awake:.1f}s, using minimum sleep time")
            else:
                print(f"\nCycle completed in {time_awake:.1f}s")
            
            sleep_seconds = actual_sleep_ms / 1000
            print(f"Entering deep sleep for {sleep_seconds:.1f} seconds...")
            print(f"Next reading in {DATA_INTERVAL} seconds ({DATA_INTERVAL/60:.1f} minutes)")
            print("Power consumption: ~10µA (vs ~80mA when awake)")
            print("="*50)
            # Deep sleep - ESP32 will restart after sleep duration
            deepsleep(actual_sleep_ms)
            # Note: deepsleep() will restart the device, so this line won't be reached
        else:
            # AC Power mode: Keep running with delay (no deep sleep)
            print(f"\nCycle completed in {time_awake:.1f}s")
            print(f"Waiting {DATA_INTERVAL} seconds until next reading...")
            print("(AC Power mode - keeping device awake)")
            print("="*50)
            time.sleep(DATA_INTERVAL)
            # Loop will continue, keeping device awake

if __name__ == "__main__":
    main()
