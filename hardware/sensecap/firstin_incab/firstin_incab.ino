/*
 * FirstIn in-cab display for the Seeed SenseCAP Indicator (D1/D1S/D1Pro/D1L, ESP32-S3 + 4" 480x480 ST7701 RGB).
 *
 *  *** UNTESTED SKELETON — best effort, written without the hardware on the desk. ***
 *  The Raspberry Pi path (hardware/incab.py) is the supported demo path.
 *
 * What it does:
 *   - joins WiFi, polls GET {FIRSTIN_BACKEND}/incab/active every 2 s
 *   - on a new plan_id: flashes the screen red/white, then renders the card
 *     (address, stories/year/construction, top 3 hazards, stairs, roof access)
 *   - user button (GPIO38, the button on the top of the case): redraw / acknowledge
 *
 * Not done here: audio. On the Indicator the buzzer + Grove ports hang off the RP2040 co-processor,
 * not the ESP32-S3. Play the voice brief from the Pi/laptop (incab.py) or a paired speaker.
 *
 * Arduino IDE setup (see hardware/README.md):
 *   Board: "ESP32S3 Dev Module" (esp32 core >= 2.0.14), PSRAM: "OPI PSRAM", Flash 8MB, USB CDC on boot: Enabled
 *   Libraries: "GFX Library for Arduino" (moononournation/Arduino_GFX, 1.4.x), "ArduinoJson" (7.x)
 *   Copy secrets.example.h -> secrets.h and fill in.
 *
 * Pin map below is from Seeed's SenseCAP Indicator Arduino examples — VERIFY against
 * https://wiki.seeedstudio.com/SenseCAP_Indicator_ESP32_Arduino/ before flashing.
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include <Arduino_GFX_Library.h>
#include "secrets.h"

// ---------- SenseCAP Indicator pins (VERIFY) ----------
#define I2C_SDA 39
#define I2C_SCL 40
#define EXPANDER_ADDR 0x20      // PCA9535 IO expander
#define EXP_LCD_CS 4            // expander pin: LCD SPI CS
#define EXP_LCD_RST 5           // expander pin: LCD reset
#define LCD_SCK 41
#define LCD_MOSI 48
#define LCD_BL 45               // backlight
#define USER_BUTTON 38

// ---------- display ----------
Arduino_DataBus *bus = new Arduino_SWSPI(GFX_NOT_DEFINED /*DC*/, GFX_NOT_DEFINED /*CS via expander*/,
                                         LCD_SCK, LCD_MOSI, GFX_NOT_DEFINED /*MISO*/);
Arduino_ESP32RGBPanel *rgbpanel = new Arduino_ESP32RGBPanel(
    18 /*DE*/, 17 /*VSYNC*/, 16 /*HSYNC*/, 21 /*PCLK*/,
    4, 3, 2, 1, 0,          /* R0..R4 */
    10, 9, 8, 7, 6, 5,      /* G0..G5 */
    15, 14, 13, 12, 11,     /* B0..B4 */
    1 /*hsync_polarity*/, 10 /*hfp*/, 8 /*hpw*/, 50 /*hbp*/,
    1 /*vsync_polarity*/, 10 /*vfp*/, 8 /*vpw*/, 20 /*vbp*/);
Arduino_RGB_Display *gfx = new Arduino_RGB_Display(
    480, 480, rgbpanel, 2 /*rotation*/, true /*auto_flush*/,
    bus, GFX_NOT_DEFINED /*RST via expander*/, st7701_type1_init_operations, sizeof(st7701_type1_init_operations));

// ---------- PCA9535 helpers (drive LCD CS/RST low/high) ----------
static uint16_t expOut = 0xFFFF;
void expWrite() {
  Wire.beginTransmission(EXPANDER_ADDR);
  Wire.write(0x02);  // output port 0
  Wire.write(expOut & 0xFF);
  Wire.write(expOut >> 8);
  Wire.endTransmission();
}
void expPin(uint8_t pin, bool high) {
  if (high) expOut |= (1 << pin); else expOut &= ~(1 << pin);
  expWrite();
}
void expInit() {
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.beginTransmission(EXPANDER_ADDR);
  Wire.write(0x06);  // config port 0: 0 = output
  Wire.write(~((1 << EXP_LCD_CS) | (1 << EXP_LCD_RST)) & 0xFF);
  Wire.write(0xFF);
  Wire.endTransmission();
  expPin(EXP_LCD_RST, false); delay(20);
  expPin(EXP_LCD_RST, true);  delay(120);
  expPin(EXP_LCD_CS, false);  // hold CS low for the ST7701 init sequence
}

// ---------- state ----------
String currentPlanId = "";
JsonDocument plan;
unsigned long lastPoll = 0;
const unsigned long POLL_MS = 2000;

void drawWrapped(const String &s, int x, int &y, int size, uint16_t color, int maxChars) {
  gfx->setTextSize(size);
  gfx->setTextColor(color);
  String rest = s;
  while (rest.length()) {
    int cut = rest.length() <= (unsigned)maxChars ? rest.length() : rest.lastIndexOf(' ', maxChars);
    if (cut <= 0) cut = min((int)rest.length(), maxChars);
    gfx->setCursor(x, y);
    gfx->print(rest.substring(0, cut));
    rest = rest.substring(cut);
    rest.trim();
    y += 10 * size;
  }
}

String hazardText(JsonVariant h) {
  if (h.is<const char *>()) return String(h.as<const char *>());
  String t = h["type"] | "";
  String l = h["location"] | "";
  return l.length() ? t + " - " + l : t;
}

void drawStatus(const char *msg) {
  gfx->fillScreen(BLACK);
  gfx->setTextSize(3);
  gfx->setTextColor(WHITE);
  gfx->setCursor(20, 20);
  gfx->print("FIRSTIN  ENGINE 12");
  gfx->setTextSize(2);
  gfx->setCursor(20, 80);
  gfx->print(msg);
}

void drawCard() {
  gfx->fillScreen(BLACK);
  gfx->fillRect(0, 0, 480, 50, RED);
  gfx->setTextColor(WHITE);
  gfx->setTextSize(3);
  gfx->setCursor(12, 14);
  gfx->print("APPROVED PRE-PLAN");

  int y = 64;
  drawWrapped(String(plan["address"] | "?"), 12, y, 3, YELLOW, 25);
  y += 6;
  String meta = String((int)(plan["stories"] | 0)) + " stories | built " + String((int)(plan["year_built"] | 0));
  drawWrapped(meta, 12, y, 2, WHITE, 38);
  drawWrapped(String(plan["construction"] | ""), 12, y, 2, WHITE, 38);
  y += 10;
  gfx->drawFastHLine(0, y, 480, DARKGREY); y += 10;
  drawWrapped("TOP HAZARDS", 12, y, 2, ORANGE, 38);
  int i = 1;
  for (JsonVariant h : plan["top_hazards"].as<JsonArray>()) {
    if (i > 3) break;
    drawWrapped(String(i++) + ". " + hazardText(h), 12, y, 2, WHITE, 38);
  }
  y += 10;
  gfx->drawFastHLine(0, y, 480, DARKGREY); y += 10;
  String stairs = plan["stairs"].is<JsonArray>() ? String("see dashboard") : String(plan["stairs"] | "VERIFY ON SITE");
  drawWrapped("STAIRS: " + stairs, 12, y, 2, CYAN, 38);
  drawWrapped("ROOF: " + String(plan["roof_access"] | "VERIFY ON SITE"), 12, y, 2, CYAN, 38);
  gfx->setTextSize(2);
  gfx->setTextColor(DARKGREY);
  gfx->setCursor(12, 450);
  gfx->print("Press button for brief (plays on rig speaker)");
}

void flashNewPlan() {
  for (int i = 0; i < 4; i++) {
    gfx->fillScreen(RED); delay(150);
    gfx->fillScreen(WHITE); delay(150);
  }
}

void poll() {
  if (WiFi.status() != WL_CONNECTED) { drawStatus("WiFi lost, reconnecting..."); WiFi.reconnect(); return; }
  HTTPClient http;
  http.setTimeout(4000);
  http.begin(String(FIRSTIN_BACKEND) + "/incab/active");
  int code = http.GET();
  if (code == 200) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, http.getStream());
    if (!err) {
      String pid = doc["plan_id"] | "";
      if (pid.length() && pid != currentPlanId) {
        currentPlanId = pid;
        plan = doc;
        Serial.printf("[incab] new plan %s\n", pid.c_str());
        flashNewPlan();
        drawCard();
      }
    } else {
      Serial.printf("[incab] json error %s\n", err.c_str());
    }
  } else if (code == 404) {
    if (currentPlanId == "") drawStatus("Waiting for an approved pre-plan...");
  } else {
    Serial.printf("[incab] HTTP %d\n", code);
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(USER_BUTTON, INPUT_PULLUP);
  pinMode(LCD_BL, OUTPUT);
  digitalWrite(LCD_BL, HIGH);
  expInit();
  if (!gfx->begin()) Serial.println("gfx->begin() failed (check pin map / PSRAM setting)");
  expPin(EXP_LCD_CS, true);
  drawStatus("Connecting to WiFi...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  drawStatus(WiFi.status() == WL_CONNECTED ? "Waiting for an approved pre-plan..." : "WiFi failed - check secrets.h");
}

void loop() {
  if (millis() - lastPoll > POLL_MS) { lastPoll = millis(); poll(); }
  static bool lastBtn = HIGH;
  bool b = digitalRead(USER_BUTTON);
  if (lastBtn == HIGH && b == LOW && currentPlanId.length()) {
    Serial.println("[incab] BRIEF ME pressed");
    drawCard();  // acknowledge; audio plays from the Pi/laptop unit
  }
  lastBtn = b;
  delay(20);
}
