import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:audioplayers/audioplayers.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  // 1. Initialize Firebase
  await Firebase.initializeApp();

  // 2. Initialize Supabase using your project targets
  await Supabase.initialize(
    url: 'https://tlsvizqmjdasvnwztlum.supabase.co',
    anonKey: 'sb_publishable_vj7kCLqt89pA8_N9s9q9Ng_BMzth30d',
  );

  runApp(const SmartParkingApp());
}

class SmartParkingApp extends StatelessWidget {
  const SmartParkingApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Parking Tracker',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF00E676),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const ParkingMonitorDashboard(),
    );
  }
}

class ParkingMonitorDashboard extends StatefulWidget {
  const ParkingMonitorDashboard({super.key});

  @override
  State<ParkingMonitorDashboard> createState() => _ParkingMonitorDashboardState();
}

class _ParkingMonitorDashboardState extends State<ParkingMonitorDashboard> {
  final _supabase = Supabase.instance.client;
  Map<String, dynamic>? _latestSnapshot;
  bool _isSubscribed = false;
  bool _isLoading = true;
  RealtimeChannel? _realtimeSubscription;
  String? _timeBasis;
  final _audioPlayer = AudioPlayer();

  @override
  void initState() {
    super.initState();
    _fetchInitialStatus();
    _initRealtimeStream();
  }

  @override
  void dispose() {
    if (_realtimeSubscription != null) {
      _supabase.removeChannel(_realtimeSubscription!);
    }
    _audioPlayer.dispose();
    super.dispose();
  }

  Future<void> _fetchInitialStatus() async {
    try {
      final response = await _supabase
          .from('parking_slots')
          .select()
          .order('captured_at', ascending: false)
          .limit(1)
          .maybeSingle();

      if (mounted) {
        setState(() {
          _latestSnapshot = response;
          _isLoading = false;
        });
        _calculateTimeBasis(response);
      }
    } catch (e) {
      debugPrint('Error fetching status: $e');
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  Future<void> _calculateTimeBasis(Map<String, dynamic>? latest) async {
    if (latest == null) return;
    final int freeSpaces = latest['free_spaces'] ?? 0;
    try {
      if (freeSpaces > 0) {
        final lastZeroRow = await _supabase
            .from('parking_slots')
            .select('captured_at')
            .eq('free_spaces', 0)
            .order('captured_at', ascending: false)
            .limit(1)
            .maybeSingle();
            
        if (lastZeroRow != null) {
          final lastZeroTime = lastZeroRow['captured_at'] as String;
          final firstFreeRow = await _supabase
              .from('parking_slots')
              .select('captured_at')
              .gt('captured_at', lastZeroTime)
              .gt('free_spaces', 0)
              .order('captured_at', ascending: true)
              .limit(1)
              .maybeSingle();
              
          if (firstFreeRow != null) {
            if (mounted) {
              setState(() => _timeBasis = firstFreeRow['captured_at'] as String);
              return;
            }
          }
        }
        
        final oldestFreeRow = await _supabase
            .from('parking_slots')
            .select('captured_at')
            .gt('free_spaces', 0)
            .order('captured_at', ascending: true)
            .limit(1)
            .maybeSingle();
        if (oldestFreeRow != null && mounted) {
          setState(() => _timeBasis = oldestFreeRow['captured_at'] as String);
        }
      } else {
        final lastFreeRow = await _supabase
            .from('parking_slots')
            .select('captured_at')
            .gt('free_spaces', 0)
            .order('captured_at', ascending: false)
            .limit(1)
            .maybeSingle();
            
        if (lastFreeRow != null && mounted) {
          setState(() => _timeBasis = lastFreeRow['captured_at'] as String);
        } else {
          if (mounted) {
            setState(() => _timeBasis = latest['captured_at'] as String);
          }
        }
      }
    } catch (e) {
      debugPrint('Error calculating time basis: $e');
      if (mounted) {
        setState(() => _timeBasis = latest['captured_at'] as String);
      }
    }
  }

  void _initRealtimeStream() {
    _realtimeSubscription = _supabase
        .channel('public:parking_slots')
        .onPostgresChanges(
          event: PostgresChangeEvent.all,
          schema: 'public',
          table: 'parking_slots',
          callback: (payload) {
            if (payload.newRecord.isNotEmpty) {
              setState(() {
                _latestSnapshot = payload.newRecord;
              });
              _calculateTimeBasis(payload.newRecord);
              
              // If user is subscribed and a space just opened up, trigger a local push alert alert banner
              if (_isSubscribed && (payload.newRecord['free_spaces'] ?? 0) > 0) {
                _triggerLocalNotification(payload.newRecord['free_spaces']);
              }
            }
          },
        )
        .subscribe();
  }

  void _triggerLocalNotification(dynamic spaces) {
    // Play an audible alert sound
    _audioPlayer.play(UrlSource('https://assets.mixkit.co/active_storage/sfx/2358/2358-preview.mp3'));

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Row(
          children: [
            const Icon(Icons.check_circle, color: Colors.white),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                'Сповіщення: $spaces повились нові паркувальні місця!',
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            ),
          ],
        ),
        backgroundColor: Colors.greenAccent[700],
        duration: const Duration(seconds: 6),
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  Future<void> _toggleNotificationSubscription() async {
    final newState = !_isSubscribed;
    final messaging = FirebaseMessaging.instance;

    try {
      if (newState) {
        // 1. Request system notification permissions
        NotificationSettings settings = await messaging.requestPermission(
          alert: true,
          badge: true,
          sound: true,
        );

        if (settings.authorizationStatus == AuthorizationStatus.denied) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Будь ласка, дозвольте сповіщення в налаштуваннях.')),
            );
          }
          return;
        }

        // 2. Fetch the real unique device token from Firebase
        String? token = await messaging.getToken();
        if (token == null) throw Exception("Failed to get FCM token");

        // 3. Register real token in Supabase
        await _supabase.from('parking_subscribers').upsert(
          {'fcm_token': token},
          onConflict: 'fcm_token',
        );
      } else {
        // Remove current device token to stop notifications
        String? token = await messaging.getToken();
        if (token != null) {
          await _supabase.from('parking_subscribers').delete().eq('fcm_token', token);
        }
      }

      if (mounted) {
        setState(() {
          _isSubscribed = newState;
        });

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              _isSubscribed
                  ? 'Підписку оформлено! Ви отримаєте сповіщення, щойно звільниться паркувальне місце.'
                  : 'Скасовано підписку на сповіщення.',
            ),
            duration: const Duration(seconds: 3),
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    } catch (e) {
      debugPrint('Subscription error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Помилка оновлення підписки. Спробуйте пізніше.')),
        );
      }
    }
  }

  String _formatElapsedTime(String? isoString) {
    if (isoString == null) return 'Unknown';
    try {
      final diff = DateTime.now().difference(DateTime.parse(isoString));
      if (diff.inSeconds < 60) return '${diff.inSeconds}с тому';
      if (diff.inMinutes < 60) return '${diff.inMinutes}хв тому';
      if (diff.inHours < 24) return '${diff.inHours}годин ${diff.inMinutes % 60}хв тому';
      return '${diff.inDays} днів';
    } catch (_) {
      return 'Невідомо';
    }
  }

  @override
  Widget build(BuildContext context) {
    final freeSpaces = _latestSnapshot?['free_spaces'] ?? 0;
    final snapshotPath = _latestSnapshot?['snapshot_path'] as String?;
    final capturedAt = _latestSnapshot?['captured_at'] as String?;
    
    // Construct public storage CDN lookup reference endpoint link
    final imageUrl = snapshotPath != null
        ? _supabase.storage.from('parking_slots').getPublicUrl(snapshotPath)
        : null;

    return Scaffold(
      appBar: AppBar(
        title: const Row(
          children: [
            Icon(Icons.local_parking, color: Color(0xFF00E676), size: 28),
            SizedBox(width: 8),
            Text('Пошук місць', style: TextStyle(fontWeight: FontWeight.bold)),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              setState(() => _isLoading = true);
              _fetchInitialStatus();
            },
          )
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _fetchInitialStatus,
              child: SingleChildScrollView(
                physics: const AlwaysScrollableScrollPhysics(),
                child: Padding(
                  key: ValueKey(snapshotPath),
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      // Status Counter Card
                      Card(
                        elevation: 4,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16),
                          side: BorderSide(
                            color: freeSpaces > 0 ? const Color(0xFF00E676) : Colors.red,
                            width: 1.5,
                          ),
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(20.0),
                          child: Column(
                            children: [
                              Text(
                                freeSpaces > 0 ? 'Вільні місця' : 'Усі місьця занято',
                                style: TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.bold,
                                  color: freeSpaces > 0 ? Colors.greenAccent[400] : Colors.redAccent,
                                  letterSpacing: 1.2,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Text(
                                '$freeSpaces',
                                style: TextStyle(
                                  fontSize: 36,
                                  fontWeight: FontWeight.bold,
                                  color: freeSpaces > 0 ? const Color(0xFF00E676) : Colors.red,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),

                      // Elapsed Duration Card
                      if (capturedAt != null)
                        Card(
                          elevation: 4,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                            side: const BorderSide(color: Colors.white24, width: 1.0),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(16.0),
                            child: Column(
                              children: [
                                Text(
                                  freeSpaces > 0 ? 'Місце з\'явилось' : 'Останнє вільне місце було',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.bold,
                                    color: Colors.grey,
                                    letterSpacing: 1.1,
                                  ),
                                ),
                                const SizedBox(height: 6),
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: [
                                    Icon(
                                      Icons.access_time_filled,
                                      size: 36,
                                      color: freeSpaces > 0 ? const Color(0xFF00E676) : Colors.amber,
                                    ),
                                    const SizedBox(width: 8),
                                    Text(
                                      _formatElapsedTime(_timeBasis ?? capturedAt),
                                      style: const TextStyle(
                                        fontSize: 22,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        ),
                      const SizedBox(height: 20),

                      // Live camera preview layer
                      const Padding(
                        padding: EdgeInsets.only(left: 4, bottom: 8),
                        child: Text(
                          'Парковка',
                          style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.grey),
                        ),
                      ),
                      GestureDetector(
                        onTap: imageUrl != null ? () {
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (context) => FullScreenImagePreview(imageUrl: imageUrl),
                            ),
                          );
                        } : null,
                        child: Card(
                          clipBehavior: Clip.antiAlias,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                          elevation: 3,
                          child: imageUrl != null
                              ? CachedNetworkImage(
                                  imageUrl: imageUrl,
                                  placeholder: (context, url) => const SizedBox(
                                    height: 220,
                                    child: Center(child: CircularProgressIndicator()),
                                  ),
                                  errorWidget: (context, url, error) => const SizedBox(
                                    height: 220,
                                    child: Center(
                                      child: Column(
                                        mainAxisAlignment: MainAxisAlignment.center,
                                        children: [
                                          Icon(Icons.broken_image, size: 48, color: Colors.grey),
                                          SizedBox(height: 8),
                                          Text('No snapshot preview available', style: TextStyle(color: Colors.grey)),
                                        ],
                                      ),
                                    ),
                                  ),
                                  fit: BoxFit.cover,
                                )
                              : const SizedBox(
                                  height: 220,
                                  child: Center(
                                    child: Text('Awaiting initial camera snapshot feed...', style: TextStyle(color: Colors.grey)),
                                  ),
                                ),
                        ),
                      ),
                      const SizedBox(height: 24),

                      // Notification subscription toggle action
                      ElevatedButton.icon(
                        onPressed: _toggleNotificationSubscription,
                        style: ElevatedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          backgroundColor: _isSubscribed ? Colors.grey[800] : const Color(0xFF00E676),
                          foregroundColor: _isSubscribed ? Colors.white : Colors.black,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        ),
                        icon: Icon(_isSubscribed ? Icons.notifications_active : Icons.notifications_none),
                        label: Text(
                          _isSubscribed
                              ? 'Відписатись від сповіщень'
                              : 'Повідомити коли появиться місце',
                          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
    );
  }
}

class FullScreenImagePreview extends StatelessWidget {
  final String imageUrl;

  const FullScreenImagePreview({super.key, required this.imageUrl});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        iconTheme: const IconThemeData(color: Colors.white),
        title: const Text('Перегляд парковки', style: TextStyle(color: Colors.white)),
      ),
      body: Center(
        child: InteractiveViewer(
          clipBehavior: Clip.none,
          minScale: 1.0,
          maxScale: 4.0,
          child: CachedNetworkImage(
            imageUrl: imageUrl,
            placeholder: (context, url) => const CircularProgressIndicator(),
            errorWidget: (context, url, error) => const Icon(Icons.broken_image, size: 64, color: Colors.grey),
            fit: BoxFit.contain,
          ),
        ),
      ),
    );
  }
}
