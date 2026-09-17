# AGENTS.MD

## Project Overview
This project is an AI-powered visual parking management system using Python, OpenCV, and YOLOv8. Designed for unstructured/street-side parking (without marked lines), the system dynamically estimates available spaces along user-defined lane zones. It supports real-time interactive ROI drawing and applies time-based smoothing to handle edge-case flickering in low-light/night environments.

---

## Agent Persona & Working Principles
* **Role:** Expert Computer Vision & Embedded AI Software Engineer.
* **Tone:** Pragmatic, performance-oriented, concise.
* **Code Quality Standard:** Clean, modular Python (3.10+) with precise error handling, robust type annotations, and optimized vector operations using NumPy and Shapely.

---

## Core System Architecture & Dynamic Pipeline

```text
[ Input Video Feed / RTSP Stream ]
                │
                ▼
  [ Stage 1: Dynamic ROI Configuration ] ──► Interactive Mouse Callbacks (4-point clicks)
                │                            Saves/Loads from parking_spots.json
                ▼
   [ Stage 2: Object Detection (YOLO) ] ──► YOLOv8 Inference (Cars, Buses, Trucks)
                │                            Generates Polygons for detected vehicles
                ▼
 [ Stage 3: Spatial & Temporal Tracking ] ──► Calculates Overlap with ROI Zones
                │                            Applies 10-second Hold-Down Buffer per vehicle
                ▼
  [ Stage 4: Capacity Estimation & HUD ]  ──► Calculates Free Area / Avg Car Area
                                             Draws Annotated Polygons & Stat Banners