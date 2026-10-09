#include <TinyGPS++.h>

TinyGPSPlus gps;

// GPS pins
#define GPS_RX 16
#define GPS_TX 17

HardwareSerial GPS(2);

// Geofence center
// CHANGE THESE VALUES TO YOUR LOCATION
const double CENTER_LAT = 27.7172;
const double CENTER_LON = 85.3240;

// Geofence radius
const double RADIUS = 50.0;   // 50 meters

void setup()
{
  Serial.begin(115200);

  GPS.begin(9600, SERIAL_8N1, GPS_RX, GPS_TX);

  Serial.println("GPS GEO-FENCE SYSTEM");
  Serial.println("--------------------");

  Serial.print("Center Latitude: ");
  Serial.println(CENTER_LAT, 6);

  Serial.print("Center Longitude: ");
  Serial.println(CENTER_LON, 6);

  Serial.println("Geofence Radius: 50 meters");
  Serial.println("Waiting for GPS...");
}

void loop()
{
  // Read GPS data
  while (GPS.available())
  {
    gps.encode(GPS.read());
  }

  // Check GPS location
  if (gps.location.isValid())
  {
    double latitude = gps.location.lat();
    double longitude = gps.location.lng();

    // Calculate distance from geofence center
    double distance = TinyGPSPlus::distanceBetween(
      latitude,
      longitude,
      CENTER_LAT,
      CENTER_LON
    );

    Serial.println("-------------------------");

    Serial.print("Latitude: ");
    Serial.println(latitude, 6);

    Serial.print("Longitude: ");
    Serial.println(longitude, 6);

    Serial.print("Distance: ");
    Serial.print(distance);
    Serial.println(" meters");

    // Geofence decision
    if (distance <= RADIUS)
    {
      Serial.println("STATUS: INSIDE GEOFENCE");
    }
    else
    {
      Serial.println("STATUS: OUTSIDE GEOFENCE");
    }
  }
  else
  {
    Serial.println("Waiting for GPS fix...");
  }

  delay(1000);
}