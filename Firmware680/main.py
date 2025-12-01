"""
BME680 Weather Monitoring Firmware for ESP32
Power-efficient version optimized for battery operation
Uses deep sleep mode to minimize power consumption
"""

from machine import Pin, I2C, deepsleep, reset
import bme680
import time
import json
import network
import urequests as requests
import socket
import _thread

# ============================================================================
# CONFIGURATION
# ============================================================================

# I2C Configuration
I2C_SCL_PIN = 22
I2C_SDA_PIN = 21
I2C_FREQ = 100000
BME680_ADDRESS = 0x76  # Change to 0x77 if your sensor uses that address

# LED Configuration (ESP32-WROOM typically uses GPIO 2)
LED_PIN = 2  # Change if your board uses a different pin

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

# AP Mode configuration
AP_MODE_DURATION = 300  # 5 minutes in seconds
AP_SSID = "BME680-Config"
AP_PASSWORD = "config1234"
WEB_SERVER_PORT = 80

# ============================================================================
# FUNCTIONS
# ============================================================================

# LED control
led = None
led_blink_thread_running = False

def init_led():
    """Initialize LED pin."""
    global led
    try:
        led = Pin(LED_PIN, Pin.OUT)
        led.off()  # Start with LED off
        print(f"LED initialized on GPIO {LED_PIN}")
    except Exception as e:
        print(f"Warning: Could not initialize LED on GPIO {LED_PIN}: {e}")
        led = None

def led_on():
    """Turn LED on."""
    global led
    if led is not None:
        try:
            led.on()
        except:
            pass

def led_off():
    """Turn LED off."""
    global led
    if led is not None:
        try:
            led.off()
        except:
            pass

def led_blink_thread(interval=0.5):
    """Blink LED in a separate thread."""
    global led, led_blink_thread_running
    led_blink_thread_running = True
    while led_blink_thread_running:
        try:
            if led is not None:
                led.on()
                time.sleep(interval)
                led.off()
                time.sleep(interval)
            else:
                time.sleep(interval * 2)
        except:
            time.sleep(interval * 2)

def start_led_blink(interval=0.5):
    """Start LED blinking in a separate thread."""
    global led_blink_thread_running
    stop_led_blink()  # Stop any existing blink thread
    try:
        _thread.start_new_thread(led_blink_thread, (interval,))
    except Exception as e:
        print(f"Warning: Could not start LED blink thread: {e}")

def stop_led_blink():
    """Stop LED blinking."""
    global led_blink_thread_running
    led_blink_thread_running = False
    time.sleep(0.1)  # Give thread time to stop

def load_wifi_config():
    """Load WiFi credentials, backend URL, port, and data interval from wifi.json file."""
    try:
        with open('wifi.json', 'r') as f:
            config = json.load(f)
            # Validate required fields - make them optional for AP mode
            if 'ssid' not in config or 'password' not in config:
                # Return default config if not set (will trigger AP mode)
                return {
                    'ssid': '',
                    'password': '',
                    'backend_url': config.get('backend_url', 'http://192.168.1.100:8811/temprec'),
                    'port': config.get('port', 8811),
                    'data_interval': config.get('data_interval', 300),
                    'onBattery': config.get('onBattery', False)
                }
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

def connect_wifi(ssid, password, max_retries=1):
    """Connect to WiFi network with retry logic."""
    wifi = network.WLAN(network.STA_IF)
    
    # Start LED blinking to indicate connection attempt
    start_led_blink(0.5)  # Blink every 0.5 seconds
    
    try:
        for attempt in range(max_retries):
            try:
                # Check if already connected
                if wifi.isconnected():
                    print(f"WiFi already connected! IP: {wifi.ifconfig()[0]}")
                    stop_led_blink()
                    led_off()  # Turn LED off when connected
                    return wifi
                
                # Reset WiFi interface if it's in a bad state
                # Check WiFi status: 0=idle, 1=connecting, 2=wrong password, 3=no AP found, etc.
                status = wifi.status()
                if status == network.STAT_CONNECTING:
                    print("  WiFi still connecting from previous attempt, disconnecting...")
                    wifi.disconnect()
                    time.sleep(1)
                
                # Activate WiFi interface
                if not wifi.active():
                    wifi.active(True)
                    time.sleep(0.5)  # Give it time to activate
                
                # Try to connect
                print(f"Connecting to WiFi '{ssid}' (attempt {attempt + 1}/{max_retries})...")
                try:
                    wifi.connect(ssid, password)
                except OSError as e:
                    # If already connecting or other error, disconnect and retry
                    if "connecting" in str(e).lower() or "sta is connecting" in str(e).lower():
                        print(f"  WiFi interface busy, resetting...")
                        wifi.disconnect()
                        wifi.active(False)
                        time.sleep(1)
                        wifi.active(True)
                        time.sleep(0.5)
                        wifi.connect(ssid, password)
                    else:
                        raise
                
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
                    stop_led_blink()
                    led_off()  # Turn LED off when connected successfully
                    return wifi
                else:
                    print("\n  Connection failed")
                    # Disconnect before retry (if max_retries > 1)
                    if attempt < max_retries - 1:
                        wifi.disconnect()
                        time.sleep(2)  # Wait before retry
                    
            except OSError as e:
                print(f"\n  WiFi error: {e}")
                # Reset WiFi interface
                try:
                    wifi.disconnect()
                    wifi.active(False)
                    time.sleep(1)
                    wifi.active(True)
                    time.sleep(0.5)
                except:
                    pass
                
                if attempt < max_retries - 1:
                    print("  Retrying after reset...")
                    time.sleep(2)
                else:
                    stop_led_blink()
                    raise RuntimeError(f"WiFi connection failed after {max_retries} attempts: {e}")
        
        stop_led_blink()
        raise RuntimeError(f"WiFi connection failed after {max_retries} attempts")
    except:
        stop_led_blink()
        raise

def ensure_wifi_connected(ssid, password):
    """Ensure WiFi is connected, reconnect if necessary."""
    wifi = network.WLAN(network.STA_IF)
    if not wifi.isconnected():
        print("WiFi disconnected, reconnecting...")
        return connect_wifi(ssid, password)
    # Make sure LED is off when connected
    stop_led_blink()
    led_off()
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

def scan_wifi_networks():
    """Scan for available WiFi networks."""
    networks = []
    sta_was_active = False
    ap_was_active = False
    
    try:
        sta = network.WLAN(network.STA_IF)
        ap = network.WLAN(network.AP_IF)
        
        # Remember current states
        sta_was_active = sta.active()
        ap_was_active = ap.active()
        
        # Disconnect STA if connected (scanning works better when not connected)
        if sta.isconnected():
            print("Disconnecting STA for scan...")
            sta.disconnect()
            time.sleep(0.5)
        
        # Make sure STA is active for scanning (required for scan to work)
        if not sta.active():
            print("Activating STA for scanning...")
            sta.active(True)
            time.sleep(1)
        
        print("Scanning for WiFi networks...")
        scan_results = sta.scan()
        print(f"Scan returned {len(scan_results)} results")
        
        # Process scan results
        for result in scan_results:
            try:
                ssid = result[0]
                if isinstance(ssid, bytes):
                    ssid = ssid.decode('utf-8')
                
                # Skip empty SSIDs and the AP mode SSID
                if ssid and ssid.strip() and ssid != AP_SSID:
                    # Get signal strength (RSSI) - result[3]
                    rssi = result[3] if len(result) > 3 else -100
                    # Check if network is encrypted - result[4]
                    encrypted = (result[4] != 0) if len(result) > 4 else True
                    networks.append({
                        'ssid': ssid,
                        'rssi': rssi,
                        'encrypted': encrypted
                    })
            except Exception as e:
                print(f"Error processing scan result: {e}")
                continue
        
        # Sort by signal strength (strongest first)
        networks.sort(key=lambda x: x['rssi'], reverse=True)
        print(f"Found {len(networks)} valid networks")
        
        # Restore original STA state if it wasn't active before
        if not sta_was_active and ap_was_active:
            # If we were in AP mode, keep STA disabled
            sta.active(False)
            time.sleep(0.5)
        
        return networks
    except Exception as e:
        print(f"Error scanning WiFi: {e}")
        import sys
        sys.print_exception(e)
        
        # Try to restore states
        try:
            if not sta_was_active:
                sta.active(False)
        except:
            pass
        
        return []

def start_ap_mode():
    """Start Access Point mode for configuration."""
    # First, disable STA mode to ensure AP mode works properly
    sta = network.WLAN(network.STA_IF)
    if sta.active():
        print("Disabling STA mode...")
        sta.disconnect()
        sta.active(False)
        time.sleep(1)  # Give it time to fully disable
    
    # Now start AP mode
    ap = network.WLAN(network.AP_IF)
    
    # Deactivate first to ensure clean start
    if ap.active():
        ap.active(False)
        time.sleep(0.5)
    
    # Activate AP mode
    ap.active(True)
    time.sleep(1)  # Give it time to activate
    
    # Configure AP with explicit settings
    try:
        # Try with channel first (some ESP32 versions support it)
        try:
            ap.config(essid=AP_SSID, password=AP_PASSWORD, authmode=network.AUTH_WPA2_PSK, channel=6)
        except TypeError:
            # If channel parameter not supported, try without it
            ap.config(essid=AP_SSID, password=AP_PASSWORD, authmode=network.AUTH_WPA2_PSK)
    except Exception as e:
        # If that fails, try minimal config
        print(f"Warning: AP config with authmode failed: {e}, trying minimal config")
        try:
            ap.config(essid=AP_SSID, password=AP_PASSWORD)
        except Exception as e2:
            print(f"Error configuring AP: {e2}")
            raise
    
    ap.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '8.8.8.8'))
    
    # Wait a moment for AP to start broadcasting
    time.sleep(2)
    
    # Verify AP is active
    if ap.active():
        ap_config = ap.ifconfig()
        print(f"\nAP Mode started!")
        print(f"  SSID: {AP_SSID}")
        print(f"  Password: {AP_PASSWORD}")
        print(f"  IP Address: {ap_config[0]}")
        print(f"  AP Active: {ap.active()}")
    else:
        print("Warning: AP mode may not have started properly")
    
    # Turn LED on solid to indicate AP mode
    stop_led_blink()
    led_on()
    return ap

def read_sensor_data(sensor):
    """Read sensor data and return as dictionary."""
    try:
        temp = sensor.temperature
        pres = sensor.pressure
        hum = sensor.humidity
        gas = sensor.gas
        aqi = calculate_aqi(gas)
        
        return {
            "temperature": round(temp, 2),
            "humidity": round(hum, 2),
            "pressure": round(pres, 2),
            "gas_resistance": int(gas),
            "aqi": aqi,
            "status": "ok"
        }
    except Exception as e:
        print(f"Error reading sensor: {e}")
        return {
            "temperature": 0,
            "humidity": 0,
            "pressure": 0,
            "gas_resistance": 0,
            "aqi": 0,
            "status": "error",
            "error": str(e)
        }

def load_html(is_ap_mode=False):
    """Load index.html file."""
    try:
        with open('index.html', 'r') as f:
            html = f.read()
            # Replace placeholder for AP mode check (handle both comment formats)
            ap_mode_value = 'true' if is_ap_mode else 'false'
            html = html.replace('const isAPMode = false; // <!--AP_MODE_CHECK-->', f'const isAPMode = {ap_mode_value};')
            return html
    except:
        # Return default HTML if file doesn't exist
        return get_default_html(is_ap_mode)

def get_default_html(is_ap_mode=False):
    """Return default HTML content."""
    ap_mode_js = 'true' if is_ap_mode else 'false'
    return """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BME680 Weather Station</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 { font-size: 28px; margin-bottom: 10px; }
        .header p { opacity: 0.9; }
        .content { padding: 30px; }
        .sensor-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .sensor-card {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .sensor-card h3 {
            font-size: 14px;
            color: #666;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .sensor-card .value {
            font-size: 32px;
            font-weight: bold;
            color: #333;
        }
        .sensor-card .unit {
            font-size: 14px;
            color: #666;
            margin-left: 5px;
        }
        .config-section {
            background: #f8f9fa;
            padding: 25px;
            border-radius: 15px;
            margin-top: 30px;
        }
        .config-section h2 {
            color: #333;
            margin-bottom: 20px;
            font-size: 22px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: 500;
        }
        .form-group input {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        .form-group input:focus,
        .form-group select:focus {
            outline: none;
            border-color: #667eea;
        }
        .form-group select {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
            background-color: white;
        }
        .form-group select:disabled {
            background-color: #f5f5f5;
            cursor: not-allowed;
        }
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .btn:disabled:hover {
            transform: none;
            box-shadow: none;
        }
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            width: 100%;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        .btn:active {
            transform: translateY(0);
        }
        .status {
            margin-top: 15px;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
            font-weight: 500;
        }
        .status.success {
            background: #d4edda;
            color: #155724;
        }
        .status.error {
            background: #f8d7da;
            color: #721c24;
        }
        .last-update {
            text-align: center;
            color: #666;
            font-size: 14px;
            margin-top: 20px;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .updating {
            animation: pulse 1s infinite;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌡️ BME680 Weather Station</h1>
            <p>Real-time Environmental Monitoring</p>
        </div>
        <div class="content">
            <div class="sensor-grid">
                <div class="sensor-card">
                    <h3>Temperature</h3>
                    <div class="value"><span id="temp">--</span><span class="unit">°C</span></div>
                </div>
                <div class="sensor-card">
                    <h3>Humidity</h3>
                    <div class="value"><span id="hum">--</span><span class="unit">%</span></div>
                </div>
                <div class="sensor-card">
                    <h3>Pressure</h3>
                    <div class="value"><span id="pres">--</span><span class="unit">hPa</span></div>
                </div>
                <div class="sensor-card">
                    <h3>Air Quality</h3>
                    <div class="value"><span id="aqi">--</span><span class="unit">AQI</span></div>
                </div>
            </div>
            
            <div class="config-section">
                <h2>WiFi Configuration</h2>
                <form id="wifiForm">
                    <div class="form-group">
                        <label for="ssid">WiFi SSID</label>
                        <select id="ssid" name="ssid" required disabled>
                            <option value="">Scanning for networks...</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="password">WiFi Password</label>
                        <input type="password" id="password" name="password" placeholder="Enter WiFi password">
                    </div>
                    <button type="submit" class="btn" id="saveBtn" disabled>💾 Save and Reboot</button>
                </form>
                <div id="status"></div>
            </div>
            
            <div class="last-update">
                Last updated: <span id="lastUpdate">--</span>
            </div>
        </div>
    </div>
    
    <script>
        let networksLoaded = false;
        
        function loadWiFiNetworks() {
            const ssidSelect = document.getElementById('ssid');
            const saveBtn = document.getElementById('saveBtn');
            
            console.log('Starting WiFi network scan...');
            
            fetch('/api/scan')
                .then(response => {
                    console.log('Scan response status:', response.status);
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    console.log('Scan data received:', data);
                    if (data.status === 'ok' && data.networks) {
                        // Clear existing options
                        ssidSelect.innerHTML = '<option value="">Select WiFi network...</option>';
                        
                        if (data.networks.length === 0) {
                            ssidSelect.innerHTML = '<option value="">No networks found</option>';
                            ssidSelect.disabled = false;
                            saveBtn.disabled = false;
                            networksLoaded = true;
                            return;
                        }
                        
                        // Add scanned networks
                        data.networks.forEach(network => {
                            const option = document.createElement('option');
                            option.value = network.ssid;
                            const signalBars = Math.min(4, Math.floor((network.rssi + 100) / 25));
                            const signalIcon = '📶'.repeat(signalBars) || '📶';
                            const lockIcon = network.encrypted ? '🔒' : '';
                            option.textContent = `${signalIcon} ${network.ssid} ${lockIcon}`;
                            ssidSelect.appendChild(option);
                        });
                        
                        // Enable form
                        ssidSelect.disabled = false;
                        saveBtn.disabled = false;
                        networksLoaded = true;
                        console.log('Networks loaded successfully');
                    } else {
                        console.error('Invalid scan response:', data);
                        ssidSelect.innerHTML = '<option value="">Error scanning networks: ' + (data.error || 'Unknown error') + '</option>';
                        ssidSelect.disabled = false;
                        saveBtn.disabled = false;
                        networksLoaded = true; // Allow manual entry if scan fails
                    }
                })
                .catch(error => {
                    console.error('Error scanning WiFi networks:', error);
                    ssidSelect.innerHTML = '<option value="">Error: Could not scan networks. Please refresh the page.</option>';
                    ssidSelect.disabled = false;
                    saveBtn.disabled = false;
                    networksLoaded = true; // Allow manual entry if scan fails
                });
        }
        
        function updateSensorData() {
            fetch('/api/sensor')
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'ok') {
                        document.getElementById('temp').textContent = data.temperature;
                        document.getElementById('hum').textContent = data.humidity;
                        document.getElementById('pres').textContent = data.pressure;
                        document.getElementById('aqi').textContent = data.aqi;
                        document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
                    }
                })
                .catch(error => {
                    console.error('Error fetching sensor data:', error);
                });
        }
        
        document.getElementById('wifiForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            if (!networksLoaded) {
                document.getElementById('status').innerHTML = '<div class="status error">Please wait for networks to load</div>';
                return;
            }
            
            const ssid = document.getElementById('ssid').value;
            const password = document.getElementById('password').value;
            const statusDiv = document.getElementById('status');
            
            if (!ssid) {
                statusDiv.innerHTML = '<div class="status error">Please select a WiFi network</div>';
                return;
            }
            
            statusDiv.innerHTML = '<div class="status">Saving configuration...</div>';
            
            fetch('/api/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ ssid: ssid, password: password })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    statusDiv.innerHTML = '<div class="status success">Configuration saved! Device will reboot in 3 seconds...</div>';
                    setTimeout(() => {
                        window.location.reload();
                    }, 3000);
                } else {
                    statusDiv.innerHTML = '<div class="status error">Error: ' + (data.error || 'Unknown error') + '</div>';
                }
            })
            .catch(error => {
                statusDiv.innerHTML = '<div class="status error">Error: ' + error.message + '</div>';
            });
        });
        
        // Load WiFi networks on page load
        loadWiFiNetworks();
        
        // Update sensor data every 10 seconds
        updateSensorData();
        setInterval(updateSensorData, 10000);
    </script>
</body>
</html>"""

def web_server_thread(sensor, wifi_config, is_ap_mode=False):
    """Web server thread to handle HTTP requests."""
    try:
        # Bind to all interfaces (0.0.0.0) to work in both AP and STA modes
        addr = socket.getaddrinfo('0.0.0.0', WEB_SERVER_PORT)[0][-1]
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(addr)
        s.listen(5)
        
        # Determine which IP to display
        sta = network.WLAN(network.STA_IF)
        ap = network.WLAN(network.AP_IF)
        
        if sta.isconnected():
            ip = sta.ifconfig()[0]
        elif ap.active():
            ip = ap.ifconfig()[0]
        else:
            ip = '0.0.0.0'
        
        print(f"Web server started on http://{ip}:{WEB_SERVER_PORT}")
        
        while True:
            try:
                cl, addr = s.accept()
                request = cl.recv(1024).decode('utf-8')
                request_line = request.split('\n')[0]
                method_path = request_line.split(' ')
                
                if len(method_path) < 2:
                    cl.close()
                    continue
                
                method = method_path[0]
                path = method_path[1]
                
                # Remove query parameters if present
                if '?' in path:
                    path = path.split('?')[0]
                
                print(f"Request: {method} {path} from {addr[0]}")
                
                # Serve index.html
                if path == '/' or path == '/index.html':
                    html = load_html(is_ap_mode)
                    cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n')
                    cl.send(html)
                
                # API endpoint for sensor data
                elif path == '/api/sensor':
                    sensor_data = read_sensor_data(sensor)
                    cl.send('HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n')
                    cl.send(json.dumps(sensor_data))
                
                # API endpoint for WiFi network scanning (only in AP mode)
                elif path == '/api/scan':
                    if not is_ap_mode:
                        # Don't scan if not in AP mode
                        error_response = {'networks': [], 'status': 'error', 'error': 'Not in AP mode'}
                        cl.send('HTTP/1.0 403 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n')
                        cl.send(json.dumps(error_response))
                    else:
                        try:
                            print("Scan request received, starting scan...")
                            networks = scan_wifi_networks()
                            response_data = {'networks': networks, 'status': 'ok'}
                            print(f"Sending {len(networks)} networks to client")
                            cl.send('HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n')
                            cl.send(json.dumps(response_data))
                        except Exception as e:
                            print(f"Error in scan endpoint: {e}")
                            import sys
                            sys.print_exception(e)
                            error_response = {'networks': [], 'status': 'error', 'error': str(e)}
                            cl.send('HTTP/1.0 500 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n')
                            cl.send(json.dumps(error_response))
                
                # API endpoint for WiFi configuration (only in AP mode)
                elif path == '/api/config' and method == 'POST':
                    if not is_ap_mode:
                        # Don't allow config changes if not in AP mode
                        cl.send('HTTP/1.0 403 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n')
                        cl.send(json.dumps({'success': False, 'error': 'Not in AP mode'}))
                        cl.close()
                        continue
                    # Read POST data
                    content_length = 0
                    for line in request.split('\n'):
                        if line.startswith('Content-Length:'):
                            content_length = int(line.split(':')[1].strip())
                            break
                    
                    # Read body
                    body = ''
                    if content_length > 0:
                        # Find where body starts
                        body_start = request.find('\r\n\r\n')
                        if body_start != -1:
                            body = request[body_start + 4:]
                            # If body is incomplete, read more
                            if len(body) < content_length:
                                remaining = content_length - len(body)
                                body += cl.recv(remaining).decode('utf-8')
                    
                    try:
                        config_data = json.loads(body)
                        new_ssid = config_data.get('ssid', '')
                        new_password = config_data.get('password', '')
                        
                        # Load current config to preserve other fields
                        try:
                            with open('wifi.json', 'r') as f:
                                current_config = json.load(f)
                        except:
                            current_config = {}
                        
                        # Update only SSID and password, preserve other fields
                        current_config['ssid'] = new_ssid
                        current_config['password'] = new_password
                        
                        # Ensure required fields exist
                        if 'backend_url' not in current_config:
                            current_config['backend_url'] = wifi_config.get('backend_url', 'http://192.168.1.100:8811/temprec')
                        if 'port' not in current_config:
                            current_config['port'] = wifi_config.get('port', 8811)
                        if 'data_interval' not in current_config:
                            current_config['data_interval'] = wifi_config.get('data_interval', 300)
                        if 'onBattery' not in current_config:
                            current_config['onBattery'] = wifi_config.get('onBattery', False)
                        
                        # Update wifi.json
                        with open('wifi.json', 'w') as f:
                            # MicroPython json.dump doesn't support indent, so we'll format manually
                            json_str = json.dumps(current_config)
                            f.write(json_str)
                        
                        # Update the shared config dict
                        wifi_config.update(current_config)
                        
                        cl.send('HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n')
                        cl.send(json.dumps({'success': True, 'message': 'Configuration saved'}))
                        cl.close()
                        
                        # Reboot after a short delay
                        print("Configuration saved, rebooting in 3 seconds...")
                        time.sleep(3)
                        reset()
                        
                    except Exception as e:
                        print(f"Error saving config: {e}")
                        import sys
                        sys.print_exception(e)
                        cl.send('HTTP/1.0 400 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n')
                        cl.send(json.dumps({'success': False, 'error': str(e)}))
                
                else:
                    cl.send('HTTP/1.0 404 Not Found\r\n\r\n')
                
                cl.close()
                
            except Exception as e:
                print(f"Error handling request: {e}")
                try:
                    cl.close()
                except:
                    pass
                
    except Exception as e:
        print(f"Web server error: {e}")
        import sys
        sys.print_exception(e)

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
        # Set a default backend URL if not specified (will be updated when WiFi is configured)
        BACKEND_URL = 'http://192.168.1.100:8811/temprec'
        print(f"Warning: backend_url not specified, using default: {BACKEND_URL}")
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
    
    # Initialize LED
    print("\nInitializing LED...")
    init_led()
    
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
    
    # Try to connect to WiFi FIRST, then start web server
    wifi_connected = False
    ap_mode_active = False
    
    try:
        if wifi_config.get('ssid') and wifi_config.get('password'):
            print("\nAttempting to connect to WiFi...")
            wifi = connect_wifi(wifi_config['ssid'], wifi_config['password'])
            wifi_connected = True
            print("WiFi connected successfully!")
            # Start web server AFTER WiFi is connected
            print("\nStarting web server...")
            try:
                _thread.start_new_thread(web_server_thread, (sensor, wifi_config, False))
                print("Web server thread started")
            except Exception as e:
                print(f"Warning: Could not start web server thread: {e}")
        else:
            print("\nNo WiFi credentials found, starting AP mode...")
            start_ap_mode()
            ap_mode_active = True
            # Start web server in AP mode
            print("\nStarting web server...")
            try:
                _thread.start_new_thread(web_server_thread, (sensor, wifi_config, True))
                print("Web server thread started")
            except Exception as e:
                print(f"Warning: Could not start web server thread: {e}")
    except (RuntimeError, OSError) as e:
        # Catch both RuntimeError and OSError from WiFi connection failures
        error_msg = str(e)
        if "WiFi connection failed" in error_msg or "Wifi" in error_msg or "wifi" in error_msg:
            print("\n" + "="*50)
            print("WiFi connection failed!")
            print(f"Error: {error_msg}")
            print("Starting AP mode for 5 minutes...")
            print("="*50)
            start_ap_mode()
            ap_mode_active = True
            wifi_connected = False
            # Start web server in AP mode
            print("\nStarting web server...")
            try:
                _thread.start_new_thread(web_server_thread, (sensor, wifi_config, True))
                print("Web server thread started")
            except Exception as e:
                print(f"Warning: Could not start web server thread: {e}")
        else:
            # For other errors, still try to start AP mode as fallback
            print(f"\nUnexpected error during WiFi connection: {e}")
            print("Starting AP mode as fallback...")
            try:
                start_ap_mode()
                ap_mode_active = True
                wifi_connected = False
                # Start web server in AP mode
                print("\nStarting web server...")
                try:
                    _thread.start_new_thread(web_server_thread, (sensor, wifi_config, True))
                    print("Web server thread started")
                except Exception as e2:
                    print(f"Warning: Could not start web server thread: {e2}")
            except Exception as ap_error:
                print(f"Failed to start AP mode: {ap_error}")
                raise
    
    # If in AP mode, wait for 5 minutes before rebooting
    if ap_mode_active and not wifi_connected:
        print(f"\nAP mode active. Waiting {AP_MODE_DURATION} seconds before reboot...")
        print("Connect to 'BME680-Config' network to configure WiFi")
        print("Password: config1234")
        print("Then visit http://192.168.4.1")
        
        # Wait for 5 minutes, but check periodically if WiFi was configured
        start_time = time.time()
        while time.time() - start_time < AP_MODE_DURATION:
            # Check if wifi.json was updated (someone configured it)
            try:
                with open('wifi.json', 'r') as f:
                    updated_config = json.load(f)
                    if updated_config.get('ssid') and updated_config.get('ssid') != wifi_config.get('ssid', ''):
                        print("WiFi configuration detected! Rebooting...")
                        time.sleep(2)
                        reset()
            except:
                pass
            
            time.sleep(5)  # Check every 5 seconds
        
        print("\n5 minutes elapsed. Rebooting device...")
        time.sleep(2)
        reset()
    
    # Main loop - runs continuously if onBattery is False, or once if True (then deep sleep)
    while True:
        # Record start time to calculate actual sleep duration
        cycle_start_time = time.time()
        
        try:
            # Ensure WiFi is connected (will reconnect if needed)
            if wifi_connected and wifi_config.get('ssid') and wifi_config.get('password'):
                print("\nChecking WiFi connection...")
                wifi = ensure_wifi_connected(wifi_config['ssid'], wifi_config['password'])
                wifi_connected = True
            else:
                # If no WiFi credentials, skip data sending but keep web server running
                print("\nNo WiFi connection available, skipping data transmission")
                print("Web server is still accessible for configuration")
                # Still read sensor for web interface
                temp = sensor.temperature
                pres = sensor.pressure
                hum = sensor.humidity
                gas = sensor.gas
                aqi = calculate_aqi(gas)
                print(f"  Temperature: {temp}°C")
                print(f"  Pressure: {pres}hPa")
                print(f"  Humidity: {hum}%")
                print(f"  Gas resistance: {gas}Ω")
                print(f"  AQI: {aqi}")
                
                # Skip sending data, just wait
                if ON_BATTERY:
                    actual_sleep_ms = int((DATA_INTERVAL - (time.time() - cycle_start_time)) * 1000)
                    if actual_sleep_ms < 1000:
                        actual_sleep_ms = 1000
                    print(f"\nEntering deep sleep for {actual_sleep_ms/1000:.1f} seconds...")
                    deepsleep(actual_sleep_ms)
                else:
                    print(f"\nWaiting {DATA_INTERVAL} seconds until next reading...")
                    time.sleep(DATA_INTERVAL)
                continue
            
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
            
            # If WiFi connection failed, start AP mode
            error_msg = str(e)
            is_wifi_error = (
                (isinstance(e, (RuntimeError, OSError)) and 
                 ("WiFi connection failed" in error_msg or "Wifi" in error_msg or "wifi" in error_msg)) or
                isinstance(e, OSError)
            )
            
            if is_wifi_error and not ap_mode_active:
                print("\n" + "="*50)
                print("WiFi connection failed in main loop!")
                print(f"Error: {error_msg}")
                print("Starting AP mode for 5 minutes...")
                print("="*50)
                try:
                    start_ap_mode()
                    ap_mode_active = True
                    wifi_connected = False
                    
                    # Wait for 5 minutes
                    start_time = time.time()
                    while time.time() - start_time < AP_MODE_DURATION:
                        try:
                            with open('wifi.json', 'r') as f:
                                updated_config = json.load(f)
                                if updated_config.get('ssid') and updated_config.get('ssid') != wifi_config.get('ssid', ''):
                                    print("WiFi configuration detected! Rebooting...")
                                    time.sleep(2)
                                    reset()
                        except:
                            pass
                        time.sleep(5)
                    
                    print("\n5 minutes elapsed. Rebooting device...")
                    time.sleep(2)
                    reset()
                except Exception as ap_error:
                    print(f"Failed to start AP mode: {ap_error}")
                    # Continue with normal error handling
        
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
