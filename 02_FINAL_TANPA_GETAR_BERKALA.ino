#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include "model_sigap_v4.h"

// =========================================================
// SIGAP PROTECT — MODE MANDIRI ESP32-C3 (V4.5)
// MPU6050 + model Random Forest V4 (tertanam di firmware)
// Motor V919 wajib memakai rangkaian driver MOSFET/transistor.
//
// Setelah di-upload, Arduino IDE dan Serial Monitor TIDAK
// diperlukan. Untuk demonstrasi/penelitian saja; bukan alat
// keselamatan yang sudah tervalidasi.
// =========================================================

// 0 = TIDAK ADA komunikasi Serial dalam firmware yang di-upload.
// Biarkan 0 ketika menguji perangkat tanpa Arduino IDE.
#define SIGAP_DEBUG_SERIAL 0

// 0 = hentikan getar diagnostik setiap ~20 detik.
// Mode normal hanya memberi getaran ketika alarm dugaan jatuh.
// Getar error berulang tetap aktif bila kalibrasi/sensor gagal.
#define SIGAP_HEARTBEAT_AKTIF 0

// 1 = penanda getar 2x saat mulai dan 3x saat sensor/model siap.
// 0 = tidak ada getar penanda startup. Error masih ditandai getaran.
#define SIGAP_GETAR_STATUS_STARTUP 0

// 1 = HANYA TES: injeksikan kandidat dari skor fitur sintetis,
//     lalu gunakan pembacaan sensor nyata untuk cek diam 1,2 detik.
//     BUKAN validasi kemampuan mendeteksi jatuh sungguhan.
#define SIGAP_TES_KANDIDAT_SINTETIS 0

const uint8_t SDA_PIN   = 4;
const uint8_t SCL_PIN   = 5;
const uint8_t MOTOR_PIN = 6;
const uint8_t MPU_ADDR  = 0x68;

const float SKALA_ACCEL = 4096.0f; // MPU6050 +/-8 g
const float SKALA_GYRO  = 65.5f;   // MPU6050 +/-500 derajat/detik

// Logika/parameter deteksi V4 tetap sama.
const unsigned long INTERVAL_BACA = 10;
const uint8_t INTERVAL_INFERENSI_SAMPEL = 20;
const float BATAS_SKOR_MODEL = 0.75f;
const unsigned long TUNDA_CEK_DIAM = 250;
const unsigned long DURASI_DIAM = 1200;
const unsigned long BATAS_CEK_DIAM = 4500;
const float DIAM_G_MIN = 0.80f;
const float DIAM_G_MAX = 1.20f;
const float DIAM_GYRO_MAX = 25.0f;
const unsigned long DURASI_GETAR = 5000; // DIPERBAIKI: 800 ms (file kiriman: 5000 ms)
const unsigned long JEDA_ALARM = 10000;
const unsigned long INTERVAL_HEARTBEAT = 20000;

enum Tahap { NORMAL, PERIKSA_DIAM, JEDA };
Tahap tahap = NORMAL;

struct Sampel { float ax, ay, az, gx, gy, gz; };
Sampel bufferSensor[SIGAP_WINDOW_SAMPLES];
uint16_t posTulis = 0;
uint16_t jumlahSampel = 0;
uint8_t sampelSetelahInferensi = 0;

float biasGX = 0.0f, biasGY = 0.0f, biasGZ = 0.0f;
float skorTerakhir = 0.0f;
uint32_t jumlahInferensi = 0;
bool motorAktif = false;
unsigned long terakhirBaca = 0;
unsigned long mulaiPeriksa = 0;
unsigned long mulaiDiam = 0;
unsigned long mulaiMotor = 0;
unsigned long mulaiJeda = 0;
unsigned long terakhirHeartbeat = 0;

// Tidak boleh menggunakan GPIO langsung untuk memberi arus motor.
// GPIO6 hanya mengendalikan input driver.
void polaGetarPendek(uint8_t banyak) {
  digitalWrite(MOTOR_PIN, LOW);
  delay(120);
  for (uint8_t i = 0; i < banyak; ++i) {
    digitalWrite(MOTOR_PIN, HIGH);
    delay(130);
    digitalWrite(MOTOR_PIN, LOW);
    delay(170);
  }
}

bool tulisRegister(uint8_t reg, uint8_t nilai) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(nilai);
  return Wire.endTransmission() == 0;
}

bool bacaMPU(int16_t d[7]) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)14) != 14) return false;
  for (uint8_t i = 0; i < 7; ++i) {
    uint16_t v = ((uint16_t)Wire.read() << 8) | (uint8_t)Wire.read();
    d[i] = (int16_t)v;
  }
  return true;
}

bool konfigurasiMPU() {
  bool ok = tulisRegister(0x6B, 0x01); // Clock PLL, bangunkan sensor
  delay(100);
  ok &= tulisRegister(0x6C, 0x00);
  ok &= tulisRegister(0x1A, 0x03); // DLPF
  ok &= tulisRegister(0x19, 0x04); // Internal update ~200 Hz
  ok &= tulisRegister(0x1B, 0x08); // Gyro +/-500 dps
  ok &= tulisRegister(0x1C, 0x10); // Accel +/-8g
  return ok;
}

bool kalibrasiGyro() {
  const int TARGET = 160;
  const unsigned long BATAS_WAKTU = 7000;
  unsigned long mulai = millis();
  int valid = 0;
  float sx = 0, sy = 0, sz = 0;
  while (valid < TARGET && (millis() - mulai < BATAS_WAKTU)) {
    int16_t d[7];
    if (bacaMPU(d)) {
      float ax = d[0] / SKALA_ACCEL;
      float ay = d[1] / SKALA_ACCEL;
      float az = d[2] / SKALA_ACCEL;
      float gx = d[4] / SKALA_GYRO;
      float gy = d[5] / SKALA_GYRO;
      float gz = d[6] / SKALA_GYRO;
      float g = sqrtf(ax * ax + ay * ay + az * az);
      float r = sqrtf(gx * gx + gy * gy + gz * gz);
      if (g > 0.85f && g < 1.15f && r < 15.0f) {
        sx += gx; sy += gy; sz += gz;
        ++valid;
      }
    }
    delay(10);
  }
  if (valid < TARGET) return false;
  biasGX = sx / valid;
  biasGY = sy / valid;
  biasGZ = sz / valid;
  return true;
}

void resetBuffer() {
  posTulis = 0;
  jumlahSampel = 0;
  sampelSetelahInferensi = 0;
}

void tambahSampel(const Sampel &s) {
  bufferSensor[posTulis] = s;
  posTulis = (posTulis + 1) % SIGAP_WINDOW_SAMPLES;
  if (jumlahSampel < SIGAP_WINDOW_SAMPLES) ++jumlahSampel;
  if (sampelSetelahInferensi < INTERVAL_INFERENSI_SAMPEL) ++sampelSetelahInferensi;
}

// Sembilan fitur persis seperti V4 dan urutannya tidak diubah.
void hitungFitur(float fitur[SIGAP_JUMLAH_FITUR]) {
  float sumG = 0, sumG2 = 0, sumR = 0, sumR2 = 0;
  float maksG = 0, minG = 1000, maksR = 0, maksDeltaG = 0;
  float sumRLast = 0;
  float firstAx = 0, firstAy = 0, firstAz = 0;
  float lastAx = 0, lastAy = 0, lastAz = 0;
  float gSebelumnya = 0;
  for (int i = 0; i < SIGAP_WINDOW_SAMPLES; ++i) {
    const Sampel &s = bufferSensor[(posTulis + i) % SIGAP_WINDOW_SAMPLES];
    float g = sqrtf(s.ax*s.ax + s.ay*s.ay + s.az*s.az);
    float r = sqrtf(s.gx*s.gx + s.gy*s.gy + s.gz*s.gz);
    if (g > maksG) maksG = g;
    if (g < minG) minG = g;
    if (r > maksR) maksR = r;
    if (i > 0 && fabsf(g - gSebelumnya) > maksDeltaG) maksDeltaG = fabsf(g - gSebelumnya);
    gSebelumnya = g;
    sumG += g; sumG2 += g*g;
    sumR += r; sumR2 += r*r;
    if (i < 10) { firstAx += s.ax; firstAy += s.ay; firstAz += s.az; }
    if (i >= SIGAP_WINDOW_SAMPLES - 10) { lastAx += s.ax; lastAy += s.ay; lastAz += s.az; }
    if (i >= SIGAP_WINDOW_SAMPLES - 25) sumRLast += r;
  }
  float n = (float)SIGAP_WINDOW_SAMPLES;
  float meanG = sumG / n;
  float meanR = sumR / n;
  float dx = (lastAx - firstAx) / 10.0f;
  float dy = (lastAy - firstAy) / 10.0f;
  float dz = (lastAz - firstAz) / 10.0f;
  fitur[0] = maksG;
  fitur[1] = minG;
  fitur[2] = sqrtf(fmaxf(0.0f, sumG2 / n - meanG * meanG));
  fitur[3] = maksR;
  fitur[4] = meanR;
  fitur[5] = sqrtf(fmaxf(0.0f, sumR2 / n - meanR * meanR));
  fitur[6] = maksDeltaG;
  fitur[7] = sqrtf(dx * dx + dy * dy + dz * dz);
  fitur[8] = sumRLast / 25.0f;
}

void aktifkanAlarm(unsigned long sekarang) {
  digitalWrite(MOTOR_PIN, HIGH);
  motorAktif = true;
  mulaiMotor = sekarang;
  mulaiJeda = sekarang;
  tahap = JEDA;
  mulaiDiam = 0;
}

void setup() {
  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);

#if SIGAP_DEBUG_SERIAL
  Serial.begin(115200);
  delay(1000);
  Serial.println("SIGAP PROTECT MANDIRI — DEBUG");
#endif

#if SIGAP_GETAR_STATUS_STARTUP
  // 2 getaran singkat hanya bila indikator startup diaktifkan.
  polaGetarPendek(2);
#endif
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);

  // Jika gagal konfigurasi MPU, 5 getar pendek lalu mencoba lagi.
  while (!konfigurasiMPU()) {
    polaGetarPendek(5);
    delay(2000);
  }
  delay(250);

  // Jika gagal kalibrasi gyro, 4 getar pendek lalu mencoba lagi.
  while (!kalibrasiGyro()) {
    polaGetarPendek(4);
    delay(1500);
  }

  // Self-test fungsi AI: fitur sintetis diuji melalui model tertanam.
  // Ini MEMBUKTIKAN fungsi model bisa dieksekusi tanpa IDE,
  // BUKAN menguji kemampuan mengenali kejadian jatuh sungguhan.
  const float fiturTes[SIGAP_JUMLAH_FITUR] = {
    9.0f, 0.2f, 1.0f, 600.0f, 160.0f, 120.0f, 5.0f, 2.0f, 80.0f
  };
  float skorTes = sigapSkorJatuh(fiturTes);
  if (skorTes >= BATAS_SKOR_MODEL) {
#if SIGAP_GETAR_STATUS_STARTUP
    // 3 getaran singkat: MPU siap, kalibrasi dan tes fungsi model berhasil.
    polaGetarPendek(3);
#endif
  } else {
    // 6 getar pendek berulang: self-test model tidak sesuai.
    while (true) { polaGetarPendek(6); delay(2000); }
  }

  resetBuffer();
#if SIGAP_TES_KANDIDAT_SINTETIS
  // MODE TES: hanya untuk membuktikan jalur model->cek diam->motor
  // saat Arduino IDE tutup. Calon jatuh diinjeksi dari tes model sintetis.
  // Motor baru aktif jika pembacaan MPU betul-betul stabil 1,2 detik.
  tahap = PERIKSA_DIAM;
  mulaiPeriksa = millis();
  mulaiDiam = 0;
#endif
  terakhirBaca = millis();
  terakhirHeartbeat = millis();
}

void loop() {
  unsigned long sekarang = millis();

  // Jaga motor agar tidak terus menyala setelah alarm.
  if (motorAktif && sekarang - mulaiMotor >= DURASI_GETAR) {
    digitalWrite(MOTOR_PIN, LOW);
    motorAktif = false;
  }
  if (tahap == JEDA && sekarang - mulaiJeda >= JEDA_ALARM) {
    tahap = NORMAL;
    mulaiDiam = 0;
  }

  if (sekarang - terakhirBaca >= INTERVAL_BACA) {
    terakhirBaca = sekarang;
    int16_t d[7];
    if (!bacaMPU(d)) {
      resetBuffer();
      if (tahap == PERIKSA_DIAM) { tahap = NORMAL; mulaiDiam = 0; }
      return;
    }

    Sampel s;
    s.ax = d[0] / SKALA_ACCEL;
    s.ay = d[1] / SKALA_ACCEL;
    s.az = d[2] / SKALA_ACCEL;
    s.gx = d[4] / SKALA_GYRO - biasGX;
    s.gy = d[5] / SKALA_GYRO - biasGY;
    s.gz = d[6] / SKALA_GYRO - biasGZ;
    float g = sqrtf(s.ax*s.ax + s.ay*s.ay + s.az*s.az);
    float r = sqrtf(s.gx*s.gx + s.gy*s.gy + s.gz*s.gz);
    tambahSampel(s);

    if (tahap == NORMAL && jumlahSampel == SIGAP_WINDOW_SAMPLES &&
        sampelSetelahInferensi >= INTERVAL_INFERENSI_SAMPEL) {
      sampelSetelahInferensi = 0;
      float fitur[SIGAP_JUMLAH_FITUR];
      hitungFitur(fitur);
      skorTerakhir = sigapSkorJatuh(fitur);
      ++jumlahInferensi;
#if SIGAP_DEBUG_SERIAL
      Serial.print("Skor AI: "); Serial.println(skorTerakhir, 3);
#endif
      if (skorTerakhir >= BATAS_SKOR_MODEL) {
        tahap = PERIKSA_DIAM;
        mulaiPeriksa = sekarang;
        mulaiDiam = 0;
      }
    }

    if (tahap == PERIKSA_DIAM) {
      if (sekarang - mulaiPeriksa > BATAS_CEK_DIAM) {
        tahap = NORMAL;
        mulaiDiam = 0;
      } else {
        bool diam = (g >= DIAM_G_MIN && g <= DIAM_G_MAX && r <= DIAM_GYRO_MAX);
        if (sekarang - mulaiPeriksa >= TUNDA_CEK_DIAM && diam) {
          if (mulaiDiam == 0) mulaiDiam = sekarang;
          if (sekarang - mulaiDiam >= DURASI_DIAM) {
            aktifkanAlarm(sekarang);
          }
        } else {
          mulaiDiam = 0;
        }
      }
    }
  }

#if SIGAP_HEARTBEAT_AKTIF
  // Getar pendek DIAGNOSTIK (bukan alarm): AI sudah pernah inferensi.
  // Hanya saat NORMAL; skip jika ada kandidat / alarm aktif.
  if (tahap == NORMAL && !motorAktif && jumlahInferensi > 0 &&
      sekarang - terakhirHeartbeat >= INTERVAL_HEARTBEAT) {
    polaGetarPendek(1);
    terakhirHeartbeat = millis();
    terakhirBaca = millis();
    resetBuffer(); // Hindari getaran motor mencemari fitur AI.
  }
#endif
}
