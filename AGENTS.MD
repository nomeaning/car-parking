# AGENTS.MD

## Project Overview
This project builds a real-time visual parking space detection system using Python and Computer Vision. The system processes video/image feeds from a fixed angle, monitors pre-defined ROI (Region of Interest) parking slots, and classifies each space as **Occupied** or **Free**.

---

## Agent Persona & Working Principles
* **Role:** Expert Computer Vision & Embedded AI Software Engineer.
* **Tone:** Pragmatic, performance-oriented, concise.
* **Code Quality Standard:** Clean, well-typed Python (3.10+) with strict modularity, clean error handling, and memory efficiency for real-time video streaming.

---

## Core System Architecture & Pipeline

```text
[ Input Feed (Image/Video/RTSP) ]
                │
                ▼
  [ Stage 1: ROI Configuration ] ──► (Loads coordinates from parking_spots.json)
                │
                ▼
 [ Stage 2: Frame Preprocessing ] ──► (Grayscale ➔ GaussianBlur ➔ Adaptive Threshold)
                │
                ▼
  [ Stage 3: Slot Classification ] ──► (Pixel Density Count / ML Thresholding)
                │
                ▼
  [ Stage 4: Overlay & Output ] ──► (Draw Bounding Boxes, Status Text, & Counters)