import flet as ft
import math
import time
import threading
import random
import asyncio

# ==========================================
# 1. Logic Modules (Merged)
# ==========================================

# --- ACWR Logic ---
def calculate_acwr(recent_load, chronic_avg):
    if chronic_avg == 0:
        return 0, "데이터 부족"
    ratio = recent_load / chronic_avg
    if ratio < 0.8:
        status = "부상 위험 (낮음) - 훈련량 부족"
    elif 0.8 <= ratio <= 1.3:
        status = "최적 훈련 구간 (Sweet Spot)"
    elif 1.3 < ratio <= 1.5:
        status = "주의 (High Load)"
    else:
        status = "경고 (부상 위험 높음)"
    return ratio, status

# --- Routine Generator ---
def generate_routine(acwr_value, user_profile=None):
    # Default routine structure
    routine = {
        "type": "Recovery",
        "target_pace": 390, # 6'30"
        "total_duration": 1800, # 30 min
        "steps": [],
        "audio_program": "recovery_run"
    }

    if user_profile and user_profile.get("level") == "beginner":
        routine["type"] = "First Run"
        routine["target_pace"] = 480 # 8'00"
        routine["total_duration"] = 1200 # 20 min
        routine["steps"] = [
            ("warmup", 300),
            ("run_walk", 600), # 1min run / 1min walk x 5
            ("cooldown", 300)
        ]
        routine["audio_program"] = "beginner_1"
    else:
        # ACWR based logic
        if acwr_value < 0.8:
            routine["type"] = "Build Up"
            routine["total_duration"] = 2400 # 40 min
            routine["steps"] = [("warmup", 600), ("run", 1200), ("cooldown", 600)]
        elif 0.8 <= acwr_value <= 1.3:
            routine["type"] = "Maintenance"
            routine["total_duration"] = 1800 # 30 min
            routine["steps"] = [("warmup", 300), ("run", 1200), ("cooldown", 300)]
        else:
            routine["type"] = "Recovery (Light)"
            routine["total_duration"] = 1200 # 20 min
            routine["steps"] = [("warmup", 300), ("jog", 600), ("cooldown", 300)]
            
    return routine

# --- GPS Tracker ---
class GPSTracker:
    def __init__(self):
        self.points = [] # list of (lat, lon, timestamp)
        self.total_distance = 0.0
        self.current_pace = 0.0
        
    def update_position(self, lat, lon):
        now = time.time()
        self.points.append((lat, lon, now))
        if len(self.points) > 1:
            prev_lat, prev_lon, _ = self.points[-2]
            dist = self.haversine_distance(prev_lat, prev_lon, lat, lon)
            if dist > 0.005: # Filter noise (< 5m)
                self.total_distance += dist

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        R = 6371.0 # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def get_pace(self, elapsed_seconds):
        if self.total_distance < 0.01:
            return 0.0
        # minutes per km
        return (elapsed_seconds / 60) / self.total_distance

# --- Audio Engine (Simplified for No Assets) ---
class AudioEngine:
    def __init__(self, page: ft.Page):
        self.page = page
        self.current_program = None
        self.has_assets = False 
        # Check if assets exist (mock check, assume false if file not found)
        # In single file mode, we often skip assets or use web URLs
        
    def set_program(self, mode, duration):
        self.current_program = {"mode": mode, "duration": duration}

    def play(self, asset_name):
        print(f"[AudioEngine] Playing: {asset_name}")
        # In a real app, page.overlay.append(ft.Audio(src=...))
        pass

    def check_coaching(self, seconds, distance, current_pace, target_pace):
        # Logic for feedback
        if seconds > 0 and seconds % 60 == 0:
            print(f"[Coach] Check: Pace {current_pace:.1f} vs Target {target_pace}")

# ==========================================
# 2. Main Views (Merged)
# ==========================================

class RunView(ft.Column):
    def __init__(self):
        super().__init__()
        self.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.spacing = 20
        
        self.title = ft.Text("SoloRunner", size=30, weight=ft.FontWeight.BOLD)
        self.timer_text = ft.Text("00:00", size=80, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY)
        self.dist_text = ft.Text("0.00 km", size=24)
        self.pace_text = ft.Text("0'00\"/km", size=24)
        
        self.training_desc = ft.Text("Loading...", color=ft.Colors.OUTLINE)
        
        self.play_btn = ft.IconButton(
            icon=ft.Icons.PLAY_CIRCLE_FILLED, 
            icon_size=100, 
            icon_color=ft.Colors.PRIMARY,
            on_click=self.toggle_timer
        )
        
        self.is_running = False
        self.seconds = 0
        self.gpstracker = GPSTracker()
        self.audio = None
        
        # Hidden GPS Bridge
        self.gps_bridge = ft.TextField(visible=False, on_change=self.handle_gps)

        self.controls = [
            ft.Container(height=20),
            self.title,
            self.training_desc,
            ft.Container(height=40),
            self.timer_text,
            ft.Row(
                [
                    ft.Column([ft.Text("거리"), self.dist_text], horizontal_alignment="center"),
                    ft.Column([ft.Text("페이스"), self.pace_text], horizontal_alignment="center"),
                ], 
                alignment=ft.MainAxisAlignment.CENTER, spacing=50
            ),
            ft.Container(height=40),
            self.play_btn,
            self.gps_bridge
        ]

    async def did_mount(self):
        # Init logic
        routine = generate_routine(1.0, {"level": "beginner"})
        self.training_desc.value = f"목표: {int(routine['total_duration']/60)}분 러닝"
        self.audio = AudioEngine(self.page)
        self.update()
        
        # Start GPS (Async await)
        await self.start_gps()

    async def start_gps(self):
        js = """
        navigator.geolocation.watchPosition(pos => {
            var bridge = document.querySelector('input[data-control-id="gps_bridge"]'); 
            // Flet control ID finding is tricky in raw JS, better relying on specific property or just mock for now if complex
            // For this single file demo, specific Flet implementation details for JS bridge might be omitted for brevity
            // But we keep the structure.
        })
        """
        # Simplified for copy-paste robustness: 
        # Real GPS needs the bridge ID. In this unified file, we might skip complex JS binding 
        # if the user just wants the UI to work on phone first.
        pass

    def handle_gps(self, e):
        pass

    def toggle_timer(self, e):
        self.is_running = not self.is_running
        self.play_btn.icon = ft.Icons.PAUSE_CIRCLE_FILLED if self.is_running else ft.Icons.PLAY_CIRCLE_FILLED
        if self.is_running:
            threading.Thread(target=self.run_timer, daemon=True).start()
        self.update()

    def run_timer(self):
        while self.is_running:
            time.sleep(1)
            self.seconds += 1
            m, s = divmod(self.seconds, 60)
            self.timer_text.value = f"{m:02d}:{s:02d}"
            try:
                self.update()
            except:
                break

class LogView(ft.Container):
    def __init__(self):
        super().__init__()
        self.content = ft.Text("러닝 기록 (준비중)", size=20)
        self.alignment = ft.alignment.center

class SetView(ft.Container):
    def __init__(self):
        super().__init__()
        self.content = ft.Text("설정 (준비중)", size=20)
        self.alignment = ft.alignment.center

# ==========================================
# 3. Main App Entry
# ==========================================

def main(page: ft.Page):
    page.title = "SoloRunner"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0

    run_view = RunView()
    log_view = LogView()
    set_view = SetView()

    body = ft.Container(content=run_view, expand=True, padding=20)

    def nav_change(e):
        idx = e.control.selected_index
        if idx == 0: body.content = run_view
        elif idx == 1: body.content = log_view
        elif idx == 2: body.content = set_view
        page.update()

    page.navigation_bar = ft.NavigationBar(
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.RUN_CIRCLE, label="Run"),
            ft.NavigationBarDestination(icon=ft.Icons.HISTORY, label="Log"),
            ft.NavigationBarDestination(icon=ft.Icons.SETTINGS, label="Set"),
        ],
        on_change=nav_change
    )
    
    page.add(body)
    page.update()

if __name__ == "__main__":
    ft.run(main, view=ft.AppView.WEB_BROWSER)
