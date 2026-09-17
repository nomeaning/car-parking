How to upgrade this to production Background Push Notifications?
The current client-side implementation requires the app to be open or running in the background.
If you want users to get notifications even when their phone is locked and the app is completely closed, you can build a production push architecture using Supabase Database Webhooks + Firebase Cloud Messaging (FCM):

1. Add a Subscription Table: Create a table (e.g. parking_subscribers) storing users' FCM Push Tokens when they toggle the button.
2. Setup a Database Webhook: Configure a trigger on your parking_slots table to fire an Edge Function whenever a new row has free_spaces > 0.
3. Send via FCM: The Edge Function reads the push tokens from parking_subscribers and sends a native push payload via Firebase Cloud Messaging directly to Apple/Android system trays.


---

# 1. Navigate to the flutter module
cd mobile_app

# 2. Get dependencies and generate the icon assets
flutter pub get
flutter pub run flutter_launcher_icons