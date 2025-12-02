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

# Sensor Power Control (GPIO to power cycle BME680)
# BME680 draws ~3.7mA, well within ESP32 GPIO 12mA recommended limit
# Set to None to disable power cycling (sensor always powered)
SENSOR_POWER_PIN = 4  # Change to None to disable, or use GPIO 4, 5, 18, 19, etc. (pins that can source 40mA)

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

# Sensor power control
sensor_power = None

def init_sensor_power():
    """Initialize sensor power control GPIO."""
    global sensor_power
    if SENSOR_POWER_PIN is not None:
        try:
            sensor_power = Pin(SENSOR_POWER_PIN, Pin.OUT)
            sensor_power.on()  # Turn sensor on by default
            print(f"Sensor power control initialized on GPIO {SENSOR_POWER_PIN}")
        except Exception as e:
            print(f"Warning: Could not initialize sensor power control: {e}")
            sensor_power = None

def power_cycle_sensor(duration_off=5.0):
    """Power cycle the BME680 sensor by turning it off and on.
    
    Args:
        duration_off: Time in seconds to keep sensor off (default: 5 seconds)
    """
    global sensor_power
    if sensor_power is None:
        return False
    try:
        print(f"Power cycling BME680 sensor (off for {duration_off}s)...")
        sensor_power.off()  # Turn sensor off
        time.sleep(duration_off)  # Wait for power to fully drain
        sensor_power.on()  # Turn sensor back on
        time.sleep(0.5)  # Wait 500ms for sensor to initialize
        print("Sensor power cycle complete")
        return True
    except Exception as e:
        print(f"Error power cycling sensor: {e}")
        return False

# Sensor error tracking (removed - any error causes immediate reboot)

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
        except Exception as e:
            print(f"LED on error (non-critical): {e}")

def led_off():
    """Turn LED off."""
    global led
    if led is not None:
        try:
            led.off()
        except Exception as e:
            print(f"LED off error (non-critical): {e}")

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
    if led is None:
        return  # Can't blink if LED not initialized
    stop_led_blink()  # Stop any existing blink thread
    try:
        _thread.start_new_thread(led_blink_thread, (interval,))
    except Exception as e:
        print(f"Warning: Could not start LED blink thread: {e}")

def stop_led_blink():
    """Stop LED blinking."""
    global led_blink_thread_running
    led_blink_thread_running = False
    time.sleep(0.15)  # Give thread time to stop

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

def reset_wifi_interface():
    """Reset WiFi interface to recover from error states."""
    wifi = network.WLAN(network.STA_IF)
    try:
        print("  Performing full WiFi interface reset...")
        wifi.disconnect()
        time.sleep(0.5)
        wifi.active(False)
        time.sleep(1)
        wifi.active(True)
        time.sleep(1)  # Give more time for interface to fully reset
        print("  WiFi interface reset complete")
    except Exception as e:
        print(f"  Warning during WiFi reset: {e}")

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
                
                # Perform full reset on first attempt or if we've had errors
                if attempt == 0 or attempt > 0:
                    reset_wifi_interface()
                
                # Activate WiFi interface
                if not wifi.active():
                    wifi.active(True)
                    time.sleep(1)  # Give more time to activate
                
                # Try to connect
                print(f"Connecting to WiFi '{ssid}' (attempt {attempt + 1}/{max_retries})...")
                try:
                    wifi.connect(ssid, password)
                except OSError as e:
                    error_str = str(e)
                    # Handle various WiFi errors
                    if "connecting" in error_str.lower() or "sta is connecting" in error_str.lower():
                        print(f"  WiFi interface busy, resetting...")
                        reset_wifi_interface()
                        wifi.connect(ssid, password)
                    elif "0x0101" in error_str or "unknown error" in error_str.lower():
                        print(f"  WiFi unknown error detected, performing aggressive reset...")
                        reset_wifi_interface()
                        time.sleep(2)  # Extra wait for unknown errors
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
                    # Check final status for debugging
                    final_status = wifi.status()
                    print(f"  Final WiFi status: {final_status}")
                    # Disconnect before retry (if max_retries > 1)
                    if attempt < max_retries - 1:
                        wifi.disconnect()
                        time.sleep(2)  # Wait before retry
                    
            except OSError as e:
                error_str = str(e)
                print(f"\n  WiFi error: {e}")
                
                # Handle unknown errors with aggressive reset
                if "0x0101" in error_str or "unknown error" in error_str.lower():
                    print("  Detected unknown WiFi error, performing aggressive reset...")
                    reset_wifi_interface()
                    time.sleep(2)  # Extra wait for unknown errors
                
                # Reset WiFi interface
                try:
                    reset_wifi_interface()
                except:
                    pass
                
                if attempt < max_retries - 1:
                    print("  Retrying after reset...")
                    time.sleep(3)  # Longer wait before retry
                else:
                    stop_led_blink()
                    raise RuntimeError(f"WiFi connection failed after {max_retries} attempts: {e}")
            except Exception as e:
                # Catch any other exceptions
                print(f"\n  Unexpected error during WiFi connection: {e}")
                reset_wifi_interface()
                if attempt < max_retries - 1:
                    print("  Retrying after reset...")
                    time.sleep(3)
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
        # Blink LED during reconnection
        try:
            start_led_blink(0.5)
        except:
            pass
        wifi = connect_wifi(ssid, password, max_retries=1)
        # LED off when connected
        try:
            stop_led_blink()
            led_off()
        except:
            pass
        return wifi
    # Make sure LED is off when connected
    try:
        stop_led_blink()
        led_off()
    except:
        pass
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
    
    if not wifi.isconnected():
        raise RuntimeError("WiFi not connected, cannot send data")
    
    print(f"Sending to {url}...")
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
        response.close()
        raise RuntimeError(f"Server returned error: {response.status_code} - {response.text}")

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
    """Start Access Point mode for configuration. Returns None on failure."""
    try:
        reset_wifi_interface()
        time.sleep(2)
        sta = network.WLAN(network.STA_IF)
        if sta.active():
            sta.disconnect()
            sta.active(False)
            time.sleep(1)
        ap = network.WLAN(network.AP_IF)
        if ap.active():
            ap.active(False)
            time.sleep(1)
        ap.active(True)
        time.sleep(2)
        try:
            ap.config(essid=AP_SSID, password=AP_PASSWORD, authmode=network.AUTH_WPA2_PSK)
        except:
            try:
                ap.config(essid=AP_SSID, password=AP_PASSWORD)
            except Exception as e:
                print(f"AP config failed: {e}")
                return None
        ap.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '8.8.8.8'))
        time.sleep(2)
        if ap.active():
            print(f"AP Mode: {AP_SSID} / {AP_PASSWORD}")
            stop_led_blink()
            led_on()
            return ap
        return None
    except Exception as e:
        print(f"AP mode error: {e}")
        return None

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

def read_sensor_safe(sensor):
    """
    Read sensor data safely. ANY error triggers fast LED blink, power cycle (5s off), then retry.
    Returns tuple: (temp, pres, hum, gas)
    Will retry indefinitely until sensor responds.
    """
    retry_count = 0
    
    while True:  # Retry indefinitely
        try:
            temp = sensor.temperature
            pres = sensor.pressure
            hum = sensor.humidity
            gas = sensor.gas
            return (temp, pres, hum, gas)
        except Exception as e:
            retry_count += 1
            print(f"\n{'='*50}")
            print(f"SENSOR ERROR (attempt {retry_count})")
            print(f"{'='*50}")
            print(f"Error: {e}")
            print(f"{'='*50}")
            
            # Fast LED blinking to indicate sensor error (0.5s on/off for 5 seconds)
            print("Flashing LED rapidly (0.5s on/off)...")
            try:
                for _ in range(10):  # Flash 10 times (5 seconds total: 0.5s on + 0.5s off each)
                    led_on()
                    time.sleep(0.5)
                    led_off()
                    time.sleep(0.5)
            except:
                pass
            
            # Power cycle sensor (off for 5 seconds)
            if power_cycle_sensor(duration_off=5.0):
                print("Retrying sensor read after power cycle...")
                # Will loop back and try reading again
            else:
                print("Power control not available, waiting 5 seconds before retry...")
                time.sleep(5.0)
                # Will loop back and try reading again

def send_chunked(cl, data, chunk_size=512):
    """Send data in chunks to avoid memory issues on ESP32."""
    try:
        # Ensure data is bytes
        if isinstance(data, str):
            data = data.encode('utf-8')
        
        # Send data in chunks
        total_sent = 0
        total_len = len(data)
        chunk_num = 0
        
        while total_sent < total_len:
            chunk = data[total_sent:total_sent + chunk_size]
            
            try:
                sent = cl.send(chunk)
                
                if sent == 0:
                    print(f"ERROR: sent 0 bytes at chunk {chunk_num}")
                    break
                
                total_sent += sent
                chunk_num += 1
                
                # Small delay every 10 chunks
                if chunk_num % 10 == 0:
                    time.sleep(0.005)
                    
            except OSError as e:
                print(f"OSError sending chunk {chunk_num}: {e}")
                break
            except Exception as e:
                print(f"Error sending chunk {chunk_num}: {e}")
                break
        
        print(f"Sent {total_sent}/{total_len} bytes in {chunk_num} chunks")
        return total_sent
    except Exception as e:
        print(f"ERROR in send_chunked: {e}")
        import sys
        sys.print_exception(e)
        return 0

def load_html(is_ap_mode=False):
    """Load index.html file."""
    try:
        with open('index.html', 'r') as f:
            html = f.read()
            # Replace placeholder for AP mode check
            ap_mode_value = 'true' if is_ap_mode else 'false'
            html = html.replace('const isAPMode = false; // <!--AP_MODE_CHECK-->', f'const isAPMode = {ap_mode_value};')
            return html
    except:
        # Return minimal HTML if file doesn't exist
        ap_mode_js = 'true' if is_ap_mode else 'false'
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>BME680</title><style>body{{font-family:Arial;margin:20px;background:#f0f0f0}}h1{{color:#333}}.card{{background:#fff;padding:15px;margin:10px 0;border-radius:5px}}.btn{{background:#4CAF50;color:#fff;border:none;padding:10px 20px;border-radius:5px;cursor:pointer;width:100%}}input,select{{width:100%;padding:8px;margin:5px 0;border:1px solid #ddd;border-radius:3px}}</style></head><body><h1>BME680 Weather</h1><div class="card"><div>Temp: <span id="temp">--</span>°C</div><div>Humidity: <span id="hum">--</span>%</div><div>Pressure: <span id="pres">--</span>hPa</div><div>AQI: <span id="aqi">--</span></div></div><div class="card"><h2>WiFi Config</h2><form id="wifiForm"><label>SSID:</label><select id="ssid" disabled><option>Scanning...</option></select><label>Password:</label><input type="password" id="password"><button type="submit" class="btn" id="saveBtn" disabled>Save</button></form><div id="status"></div></div><script>const isAPMode={ap_mode_js};let n=false;function l(){{const s=document.getElementById('ssid'),b=document.getElementById('saveBtn');fetch('/api/scan').then(r=>r.json()).then(d=>{{if(d.status==='ok'&&d.networks){{s.innerHTML='<option value="">Select...</option>';d.networks.forEach(n=>{{const o=document.createElement('option');o.value=n.ssid;o.textContent=n.ssid+(n.encrypted?' [Locked]':'');s.appendChild(o)}});s.disabled=false;b.disabled=false;n=true}}}}).catch(e=>{{s.innerHTML='<option>Error</option>';s.disabled=false;b.disabled=false;n=true}});}}function u(){{fetch('/api/sensor').then(r=>r.json()).then(d=>{{if(d.status==='ok'){{document.getElementById('temp').textContent=d.temperature;document.getElementById('hum').textContent=d.humidity;document.getElementById('pres').textContent=d.pressure;document.getElementById('aqi').textContent=d.aqi;}}}});}}document.getElementById('wifiForm').addEventListener('submit',function(e){{e.preventDefault();if(!n)return;const s=document.getElementById('ssid').value,p=document.getElementById('password').value;if(!s){{document.getElementById('status').innerHTML='Select network';return;}}document.getElementById('status').innerHTML='Saving...';fetch('/api/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{ssid:s,password:p}})}}).then(r=>r.json()).then(d=>{{if(d.success){{document.getElementById('status').innerHTML='Saved! Rebooting...';setTimeout(()=>location.reload(),2000);}}else{{document.getElementById('status').innerHTML='Error: '+d.error;}}}}).catch(e=>{{document.getElementById('status').innerHTML='Error: '+e.message;}});}});if(isAPMode)l();u();setInterval(u,10000);</script></body></html>"""

def web_server_thread(sensor, wifi_config, is_ap_mode=False):
    """Web server thread to handle HTTP requests."""
    s = None
    try:
        # Wait a moment for network interface to be fully ready (especially important for AP mode)
        time.sleep(1)
        
        # Determine which IP to display
        sta = network.WLAN(network.STA_IF)
        ap = network.WLAN(network.AP_IF)
        
        if sta.isconnected():
            ip = sta.ifconfig()[0]
        elif ap.active():
            ip = ap.ifconfig()[0]
            # Extra wait for AP mode to ensure it's fully ready
            time.sleep(1)
        else:
            ip = '0.0.0.0'
        
        # Bind to all interfaces (0.0.0.0) to work in both AP and STA modes
        print(f"Binding web server to 0.0.0.0:{WEB_SERVER_PORT}...")
        addr = socket.getaddrinfo('0.0.0.0', WEB_SERVER_PORT)[0][-1]
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Set socket to blocking mode (default, but explicit)
        s.setblocking(True)
        s.bind(addr)
        s.listen(5)
        
        print(f"Web server started on http://{ip}:{WEB_SERVER_PORT}")
        print(f"Server is listening and ready to accept connections")
        
        while True:
            try:
                cl, addr = s.accept()
                # Set client socket to blocking and add timeout
                cl.setblocking(True)
                # Set a reasonable timeout for receiving data
                cl.settimeout(5.0)
                
                request = cl.recv(1024).decode('utf-8')
                if not request:
                    cl.close()
                    continue
                    
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
                
                # Test endpoint
                if path == '/test':
                    cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nTest OK - Server is working!')
                    cl.close()
                    continue
                
                # Serve index.html
                if path == '/' or path == '/index.html':
                    try:
                        print("Serving HTML file...")
                        
                        # Send headers first
                        headers = 'HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n'
                        cl.send(headers)
                        
                        # Try to read and send file directly in chunks (more memory efficient)
                        file_sent = False
                        try:
                            print("Opening index.html...")
                            with open('index.html', 'r') as f:
                                # Read and send file in chunks directly
                                chunk_size = 512
                                total_sent = 0
                                ap_mode_replaced = False
                                ap_mode_value = 'true' if is_ap_mode else 'false'
                                
                                while True:
                                    chunk = f.read(chunk_size)
                                    if not chunk:
                                        break
                                    
                                    # Replace AP mode placeholder on first chunk if needed
                                    if not ap_mode_replaced and 'const isAPMode = false; // <!--AP_MODE_CHECK-->' in chunk:
                                        chunk = chunk.replace('const isAPMode = false; // <!--AP_MODE_CHECK-->', f'const isAPMode = {ap_mode_value};')
                                        ap_mode_replaced = True
                                    
                                    # Send chunk
                                    sent = cl.send(chunk)
                                    if sent == 0:
                                        print("Connection closed during send")
                                        break
                                    total_sent += sent
                                
                                print(f"File sent: {total_sent} bytes")
                                file_sent = True
                                
                        except OSError as e:
                            print(f"File not found: {e}, using default HTML")
                        except Exception as e:
                            print(f"Error reading file: {e}")
                            import sys
                            sys.print_exception(e)
                        
                        # If file sending failed, use default HTML
                        if not file_sent:
                            print("Using default HTML...")
                            html = load_html(is_ap_mode)
                            bytes_sent = send_chunked(cl, html, chunk_size=512)
                            print(f"Default HTML sent: {bytes_sent} bytes")
                            
                    except Exception as e:
                        print(f"ERROR serving HTML: {e}")
                        import sys
                        sys.print_exception(e)
                        try:
                            cl.send('HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nServer Error')
                        except:
                            pass
                
                # API endpoint for sensor data
                elif path == '/api/sensor':
                    sensor_data = read_sensor_data(sensor)
                    response = 'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n' + json.dumps(sensor_data)
                    cl.send(response)
                
                # API endpoint for WiFi network scanning (only in AP mode)
                elif path == '/api/scan':
                    if not is_ap_mode:
                        # Don't scan if not in AP mode
                        error_response = {'networks': [], 'status': 'error', 'error': 'Not in AP mode'}
                        response = 'HTTP/1.0 403 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n' + json.dumps(error_response)
                        cl.send(response)
                    else:
                        try:
                            print("Scan request received, starting scan...")
                            networks = scan_wifi_networks()
                            response_data = {'networks': networks, 'status': 'ok'}
                            print(f"Sending {len(networks)} networks to client")
                            response = 'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n' + json.dumps(response_data)
                            cl.send(response)
                        except Exception as e:
                            print(f"Error in scan endpoint: {e}")
                            import sys
                            sys.print_exception(e)
                            error_response = {'networks': [], 'status': 'error', 'error': str(e)}
                            response = 'HTTP/1.0 500 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n' + json.dumps(error_response)
                            cl.send(response)
                
                # API endpoint for WiFi configuration (only in AP mode)
                elif path == '/api/config' and method == 'POST':
                    if not is_ap_mode:
                        # Don't allow config changes if not in AP mode
                        response = 'HTTP/1.0 403 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n' + json.dumps({'success': False, 'error': 'Not in AP mode'})
                        cl.send(response)
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
                        
                        response = 'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n' + json.dumps({'success': True, 'message': 'Configuration saved'})
                        cl.send(response)
                        cl.close()
                        
                        # Reboot after a short delay
                        print("Configuration saved, rebooting in 3 seconds...")
                        time.sleep(3)
                        reset()
                        
                    except Exception as e:
                        print(f"Error saving config: {e}")
                        import sys
                        sys.print_exception(e)
                        response = 'HTTP/1.0 400 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n' + json.dumps({'success': False, 'error': str(e)})
                        cl.send(response)
                
                else:
                    # 404 Not Found
                    cl.send('HTTP/1.0 404 Not Found\r\nContent-Type: text/plain\r\n\r\n404 Not Found')
                
                # Close connection after response
                cl.close()
                print(f"Connection closed for {method} {path}")
                
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
        if s is not None:
            try:
                s.close()
            except:
                pass

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
    
    # Initialize sensor power control
    print("\nInitializing sensor power control...")
    init_sensor_power()
    
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
    
    if wifi_config.get('ssid') and wifi_config.get('password'):
        print("\nAttempting to connect to WiFi...")
        try:
            # Use 3 retries during initialization for better reliability
            wifi = connect_wifi(wifi_config['ssid'], wifi_config['password'], max_retries=3)
            wifi_connected = True
            print("WiFi connected successfully!")
            # Start web server AFTER WiFi is connected
            print("\nStarting web server...")
            _thread.start_new_thread(web_server_thread, (sensor, wifi_config, False))
            print("Web server thread started")
        except Exception as e:
            print(f"\n{'='*50}")
            print("WiFi connection failed during initialization")
            print(f"Error: {e}")
            print(f"{'='*50}")
            print("Falling back to AP mode for configuration...")
            print(f"{'='*50}\n")
            # Fall back to AP mode instead of crashing
            ap = start_ap_mode()
            if ap:
                ap_mode_active = True
                print("\nStarting web server...")
                _thread.start_new_thread(web_server_thread, (sensor, wifi_config, True))
                time.sleep(2)
            else:
                print("AP mode failed. Rebooting in 5s...")
                time.sleep(5)
                reset()
    else:
        print("\nNo WiFi credentials found, starting AP mode...")
        ap = start_ap_mode()
        if ap:
            ap_mode_active = True
            print("\nStarting web server...")
            _thread.start_new_thread(web_server_thread, (sensor, wifi_config, True))
            time.sleep(2)
        else:
            print("AP mode failed. Rebooting in 5s...")
            time.sleep(5)
            reset()
    
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
            except Exception as e:
                print(f"Error checking wifi.json: {e}")
                # On any error reading config, reboot
                print("Rebooting due to config read error...")
                time.sleep(2)
                reset()
            
            time.sleep(5)  # Check every 5 seconds
        
        print("\n5 minutes elapsed. Rebooting device...")
        time.sleep(2)
        reset()
    
    # Main loop - runs continuously if onBattery is False, or once if True (then deep sleep)
    cycle_count = 0
    while True:
        cycle_count += 1
        # Record start time to calculate actual sleep duration
        cycle_start_time = time.time()
        
        print(f"\n{'='*50}")
        print(f"Main loop cycle #{cycle_count}")
        print(f"{'='*50}")
        
        try:
            # Ensure WiFi is connected (will reconnect if needed)
            if wifi_config.get('ssid') and wifi_config.get('password'):
                print("\nChecking WiFi connection...")
                wifi = ensure_wifi_connected(wifi_config['ssid'], wifi_config['password'])
                wifi_connected = True
                # LED off when connected
                try:
                    stop_led_blink()
                    led_off()
                except:
                    pass
            else:
                # If no WiFi credentials, skip data sending but keep web server running
                print("\nNo WiFi connection available, skipping data transmission")
                print("Web server is still accessible for configuration")
                # Still read sensor for web interface
                print("Reading sensor...")
                temp, pres, hum, gas = read_sensor_safe(sensor)
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
            temp, pres, hum, gas = read_sensor_safe(sensor)
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
            # Any error in send_data will raise exception and trigger reboot
            print("\nSending data to server...")
            send_data(BACKEND_URL, data, wifi, wifi_config['ssid'], wifi_config['password'])
            print("✓ Success!")
            # Quick LED blink to indicate success
            try:
                led_on()
                time.sleep(0.1)
                led_off()
            except:
                pass
            
            # Verify WiFi is still connected - if not, log warning
            wifi = network.WLAN(network.STA_IF)
            if not wifi.isconnected():
                print("Warning: WiFi disconnected after sending data, will reconnect on next cycle")
            
        except Exception as e:
            print(f"\n{'='*50}")
            print("ERROR in main loop - Continuing to next cycle")
            print(f"{'='*50}")
            print(f"Error: {e}")
            import sys
            sys.print_exception(e)
            print(f"{'='*50}")
            print("Waiting before next cycle...")
            print(f"{'='*50}\n")
            
            # Blink LED to indicate error
            try:
                for _ in range(5):
                    led_on()
                    time.sleep(0.2)
                    led_off()
                    time.sleep(0.2)
            except:
                pass
            
            # Wait before continuing to next cycle
            time.sleep(5)
            # Continue to next cycle instead of rebooting
        
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
            print(f"\nCycle #{cycle_count} completed in {time_awake:.1f}s")
            print(f"Waiting {DATA_INTERVAL} seconds until next reading...")
            print("(AC Power mode - keeping device awake)")
            print("="*50)
            
            # Show periodic status during wait
            wait_start = time.time()
            status_interval = 30  # Show status every 30 seconds
            while time.time() - wait_start < DATA_INTERVAL:
                remaining = DATA_INTERVAL - (time.time() - wait_start)
                if remaining <= status_interval:
                    # Last status before next cycle
                    print(f"Next cycle in {remaining:.0f} seconds...")
                    break
                time.sleep(status_interval)
                remaining = DATA_INTERVAL - (time.time() - wait_start)
                print(f"[Status] Waiting... {remaining:.0f} seconds until next cycle")
            
            # Loop will continue, keeping device awake

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n{'='*50}")
        print("FATAL ERROR during initialization")
        print(f"{'='*50}")
        print(f"Error: {e}")
        import sys
        sys.print_exception(e)
        print(f"{'='*50}")
        print("Waiting 10 seconds before retry...")
        print(f"{'='*50}\n")
        
        # Blink LED rapidly to indicate error
        try:
            led = Pin(LED_PIN, Pin.OUT)
            for _ in range(10):
                led.on()
                time.sleep(0.5)
                led.off()
                time.sleep(0.5)
        except:
            pass
        
        time.sleep(10)
        # Retry initialization instead of rebooting
        try:
            main()
        except:
            # If still failing, just wait and retry again
            print("Retry failed, waiting 30 seconds...")
            time.sleep(30)
            reset()  # Only reboot as last resort after multiple failures
