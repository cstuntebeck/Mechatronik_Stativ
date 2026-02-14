#include <Arduino.h>
#include <AccelStepper.h>

// Pins für Motor 1 (X-Achse)
const int PUL_X = 4;
const int DIR_X = 5;
const int ENA_X = 6;

// Pins für Motor 2 (Y-Achse)
const int PUL_Y = 15;
const int DIR_Y = 16;
const int ENA_Y = 17;

const int ledPin = 13; // Pin für die Heartbeat-LED
unsigned long lastLedToggle = 0; // Zeitstempel für nicht-blockierende LED

// AccelStepper Instanzen (DRIVER mode for TB6600)
AccelStepper stepperX(AccelStepper::DRIVER, PUL_X, DIR_X);
AccelStepper stepperY(AccelStepper::DRIVER, PUL_Y, DIR_Y);

void setup() {
  Serial.begin(115200);

  // Enable Pins initialisieren und Motoren aktivieren
  pinMode(ENA_X, OUTPUT);
  digitalWrite(ENA_X, LOW);
  pinMode(ENA_Y, OUTPUT);
  digitalWrite(ENA_Y, LOW);

  // AccelStepper-Parameter für sanfte Bewegung
  stepperX.setMaxSpeed(4000.0);      // Maximale Geschwindigkeit in Schritten/Sekunde
  stepperX.setAcceleration(2000.0); // Beschleunigung in Schritten/Sekunde^2

  stepperY.setMaxSpeed(4000.0);
  stepperY.setAcceleration(2000.0);

  pinMode(ledPin, OUTPUT);
}

void loop() {
  // Die Motoren müssen kontinuierlich "betrieben" werden, um Schritte auszuführen.
  stepperX.run();
  stepperY.run();

  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command.startsWith("move_x ")) {
      int stepsToMove = command.substring(7).toInt();
      stepperX.move(stepsToMove);
      Serial.println("OK"); // OK sofort senden
    }
    else if (command.startsWith("move_y ")) {
      int stepsToMove = command.substring(7).toInt();
      stepperY.move(stepsToMove);
      Serial.println("OK"); // OK sofort senden
    }
    else {
      Serial.println("UNKNOWN COMMAND");
    }
  }

  // Heartbeat-LED (nicht-blockierend)
  if (millis() - lastLedToggle > 500) {
    lastLedToggle = millis();
    digitalWrite(ledPin, !digitalRead(ledPin));
  }
}
