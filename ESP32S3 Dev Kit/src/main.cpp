// Pins für Motor 1
const int PUL_X = 4;
const int DIR_X = 5;
const int ENA_X = 6;

// Pins für Motor 2
const int PUL_Y = 15;
const int DIR_Y = 16;
const int ENA_Y = 17;

void setup() {
  Serial.begin(115200);

  // Motor 1 Pins initialisieren
  pinMode(PUL_X, OUTPUT);
  pinMode(DIR_X, OUTPUT);
  pinMode(ENA_X, OUTPUT);
  digitalWrite(ENA_X, LOW); // Motor 1 aktivieren

  // Motor 2 Pins initialisieren
  pinMode(PUL_Y, OUTPUT);
  pinMode(DIR_Y, OUTPUT);
  pinMode(ENA_Y, OUTPUT);
  digitalWrite(ENA_Y, LOW); // Motor 2 aktivieren

  Serial.println("TB6600 Steuerung mit ESP32-S3 gestartet");
}

void stepMotor(int pulPin, int dirPin, bool dir, int steps) {
  digitalWrite(dirPin, dir);
  for (int i = 0; i < steps; i++) {
    digitalWrite(pulPin, HIGH);
    delayMicroseconds(500);
    digitalWrite(pulPin, LOW);
    delayMicroseconds(500);
  }
}

void loop() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command.startsWith("move_x ")) {
      int stepsToMove = command.substring(6).toInt();
      bool direction = (stepsToMove > 0);
      int stepsAbs = abs(stepsToMove);

      Serial.print("Bewege X-Motor um ");
      Serial.print(stepsAbs);
      Serial.print(" Schritte ");
      Serial.println(direction ? "vorwärts" : "rückwärts");

      stepMotor(PUL_X, DIR_X, direction, stepsAbs);
      Serial.println("OK");
    }
    else if (command.startsWith("move_y ")) {
      int stepsToMove = command.substring(6).toInt();
      bool direction = (stepsToMove > 0);
      int stepsAbs = abs(stepsToMove);

      Serial.print("Bewege Y-Motor um ");
      Serial.print(stepsAbs);
      Serial.print(" Schritte ");
      Serial.println(direction ? "vorwärts" : "rückwärts");

      stepMotor(PUL_Y, DIR_Y, direction, stepsAbs);
      Serial.println("OK");
    }
    else {
      Serial.println("UNKNOWN COMMAND");
    }
  }
}
