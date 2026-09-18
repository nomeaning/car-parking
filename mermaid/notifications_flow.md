# Notification System Architecture

This diagram illustrates the flow of the parking notification system, from user subscription to the delivery of background push notifications via Firebase.

```mermaid
sequenceDiagram
    participant App as Flutter Mobile App
    participant SupabaseDB as Supabase Database
    participant EdgeFunc as Supabase Edge Function
    participant PythonAI as Python Analyzer (AI)
    participant FCM as Firebase Cloud Messaging
    participant OS as Device OS (iOS/Android)

    Note over App, OS: Step 1: User Subscription
    App->>OS: Request Notification Permissions
    OS-->>App: Permissions Granted
    App->>FCM: Fetch Device Push Token
    FCM-->>App: Returns unique token (fcm_token)
    App->>SupabaseDB: upsert into parking_subscribers (fcm_token)
    SupabaseDB-->>App: Success

    Note over App, OS: Step 2: Detection & Trigger
    PythonAI->>PythonAI: Analyzes frame, finds free spots
    PythonAI->>SupabaseDB: insert into parking_slots (free_spaces > 0)
    SupabaseDB->>SupabaseDB: trigger: notify_subscribers_on_free_space()
    SupabaseDB->>EdgeFunc: POST Webhook (free_spaces count)

    Note over App, OS: Step 3: Notification Dispatch
    EdgeFunc->>SupabaseDB: SELECT * FROM parking_subscribers
    SupabaseDB-->>EdgeFunc: List of tokens
    EdgeFunc->>EdgeFunc: Generate Google Auth JWT (Service Account)
    EdgeFunc->>FCM: POST /messages:send (with tokens)
    FCM->>OS: Delivers push notification
    OS->>App: Displays system tray alert
```

### Component Details:
1. **Flutter Mobile App:** Handles user intent, OS permissions, and registration of the physical device address in the cloud.
2. **Supabase Database:** Acts as the central state store and event bus. A PL/pgSQL trigger selectively fires only when the parking status changes from full to available.
3. **Supabase Edge Function:** A serverless Deno runtime that performs secure tasks (FCM authentication) that shouldn't be handled directly in the database.
4. **Python Analyzer:** The AI brain that continuously monitors the RTSP stream. It is "status-change-aware" to avoid flooding the database with identical heartbeats.
5. **Firebase Cloud Messaging (FCM):** The delivery infrastructure provided by Google that handles routing the message to the correct physical device across any network.
