"""
Codefolio - Kivy Desktop App Skeleton (codefolio_main.py)

Fully integrated with backend.py for scanning repos, generating
portfolio-ready summaries, live progress, and logging.

Run:
    python codefolio_main.py
"""

import os
import json
import threading
import time
from pathlib import Path

from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.properties import StringProperty, BooleanProperty, ListProperty, NumericProperty
from kivy.clock import mainthread

from backend import run_full_scan

# --- KV layout (single-file) ---
KV = '''
ScreenManager:
    HomeScreen:
    SettingsScreen:
    LogsScreen:
    OutputScreen:

<HomeScreen>:
    name: 'home'
    BoxLayout:
        orientation: 'vertical'
        padding: 12
        spacing: 12

        BoxLayout:
            size_hint_y: None
            height: '48dp'
            spacing: 8
            Button:
                text: 'Settings'
                on_release: app.root.current = 'settings'
            Button:
                text: 'Logs'
                on_release: app.root.current = 'logs'
            Button:
                text: 'Output'
                on_release: app.root.current = 'output'

        Label:
            text: 'Codefolio — Scan & Index your GitHub projects'
            size_hint_y: None
            height: '32dp'

        BoxLayout:
            size_hint_y: None
            height: '120dp'
            spacing: 12

            BoxLayout:
                orientation: 'vertical'
                spacing: 6
                Label:
                    text: 'Repos found: ' + str(root.repos_found)
                Label:
                    text: 'Projects scanned: ' + str(root.scanned_count)
                Label:
                    text: 'Output files: ' + str(root.output_count)

            BoxLayout:
                orientation: 'vertical'
                Button:
                    text: 'Start Scan'
                    on_release: root.on_start_scan()
                Button:
                    text: 'Stop (not implemented)'
                    on_release: root.log('Stop requested — not implemented')

        ProgressBar:
            id: progress
            value: root.progress
            max: 100
            size_hint_y: None
            height: '24dp'

        Label:
            text: root.status_message
            size_hint_y: None
            height: '24dp'

<SettingsScreen>:
    name: 'settings'
    BoxLayout:
        orientation: 'vertical'
        padding: 12
        spacing: 8

        BoxLayout:
            size_hint_y: None
            height: '48dp'
            Button:
                text: 'Back'
                on_release: app.root.current = 'home'
            Button:
                text: 'Save Config'
                on_release: root.save_config()

        BoxLayout:
            orientation: 'vertical'
            spacing: 6

            Label:
                text: 'GitHub Personal Access Token (repo scope required for private repos)'
                size_hint_y: None
                height: '18dp'
            TextInput:
                id: gh_token
                text: root.gh_token
                password: True
                multiline: False
                on_text: root.gh_token = self.text

            Label:
                text: 'OpenAI API Key (optional, for AI summaries)'
                size_hint_y: None
                height: '18dp'
            TextInput:
                id: openai_key
                text: root.openai_key
                password: True
                multiline: False
                on_text: root.openai_key = self.text

            Label:
                text: 'Portfolio repo (where README/index will be committed):'
                size_hint_y: None
                height: '18dp'
            TextInput:
                id: portfolio_repo
                text: root.portfolio_repo
                multiline: False
                on_text: root.portfolio_repo = self.text

            BoxLayout:
                size_hint_y: None
                height: '36dp'
                spacing: 8
                CheckBox:
                    id: include_private
                    active: root.include_private
                    on_active: root.include_private = self.active
                Label:
                    text: 'Include private repos'

            BoxLayout:
                size_hint_y: None
                height: '36dp'
                spacing: 8
                CheckBox:
                    id: use_ai
                    active: root.use_ai
                    on_active: root.use_ai = self.active
                Label:
                    text: 'Use AI summaries (requires OpenAI key)'

<LogsScreen>:
    name: 'logs'
    BoxLayout:
        orientation: 'vertical'
        padding: 12
        spacing: 8
        BoxLayout:
            size_hint_y: None
            height: '48dp'
            Button:
                text: 'Back'
                on_release: app.root.current = 'home'
        ScrollView:
            do_scroll_x: False
            Label:
                id: logs_label
                text: root.log_text
                text_size: self.width, None
                size_hint_y: None
                height: self.texture_size[1]

<OutputScreen>:
    name: 'output'
    BoxLayout:
        orientation: 'vertical'
        padding: 12
        spacing: 8
        BoxLayout:
            size_hint_y: None
            height: '48dp'
            Button:
                text: 'Back'
                on_release: app.root.current = 'home'
            Button:
                text: 'Open Output Folder'
                on_release: root.open_output_folder()
        ScrollView:
            GridLayout:
                id: outputs_grid
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                row_default_height: '28dp'
                row_force_default: True
                spacing: 6
'''

# --- Screens ---
class HomeScreen(Screen):
    repos_found = NumericProperty(0)
    scanned_count = NumericProperty(0)
    output_count = NumericProperty(0)
    progress = NumericProperty(0)
    status_message = StringProperty('Idle')

    def on_start_scan(self):
        self.log('Starting scan...')
        self.status_message = 'Starting scan'
        self.progress = 0
        t = threading.Thread(target=self._scan_worker, daemon=True)
        t.start()

    def _scan_worker(self):
        app = App.get_running_app()
        cfg = {
            "github_token": app.config_data.get("github_token"),
            "openai_key": app.config_data.get("openai_key"),
            "include_private": app.config_data.get("include_private", True),
            "portfolio_repo": app.config_data.get("portfolio_repo"),
            "output_dir": app.output_dir,
            "auto_commit": False,
            "dry_run": True
        }

        def cb(progress_tuple):
            stage, pct, message = progress_tuple
            self.log(message)
            self.update_progress(pct)

        run_full_scan(cfg, progress_callback=cb)
        self.log("All repositories scanned.")
        self.scanned_count = len(list(Path(app.output_dir).glob("*")))
        self.output_count = len(list((Path(app.output_dir)/"summaries").glob("*.md")))
        self.status_message = "Idle"

    @mainthread
    def update_progress(self, value: int):
        self.progress = value

    @mainthread
    def log(self, message: str):
        logs_screen = self.manager.get_screen('logs')
        logs_screen.append_log(message)

class SettingsScreen(Screen):
    gh_token = StringProperty('')
    openai_key = StringProperty('')
    portfolio_repo = StringProperty('jyasi-projects-index')
    include_private = BooleanProperty(True)
    use_ai = BooleanProperty(False)

    def on_pre_enter(self):
        app = App.get_running_app()
        cfg = app.config_data
        self.gh_token = cfg.get('github_token', '')
        self.openai_key = cfg.get('openai_key', '')
        self.portfolio_repo = cfg.get('portfolio_repo', 'jyasi-projects-index')
        self.include_private = cfg.get('include_private', True)
        self.use_ai = cfg.get('use_ai', False)

    def save_config(self):
        app = App.get_running_app()
        cfg = app.config_data
        cfg['github_token'] = self.gh_token
        cfg['openai_key'] = self.openai_key
        cfg['portfolio_repo'] = self.portfolio_repo
        cfg['include_private'] = self.include_private
        cfg['use_ai'] = self.use_ai
        app.save_config()
        self.manager.current = 'home'

class LogsScreen(Screen):
    log_text = StringProperty('')

    def append_log(self, message: str):
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        self.log_text += f"[{ts}] {message}\n"

class OutputScreen(Screen):
    def on_pre_enter(self):
        self.populate_outputs()

    def populate_outputs(self):
        app = App.get_running_app()
        grid = self.ids.outputs_grid
        grid.clear_widgets()
        out_dir = Path(app.output_dir)/"summaries"
        if not out_dir.exists():
            return
        for p in sorted(out_dir.iterdir()):
            if p.is_file():
                from kivy.uix.label import Label
                btn = Label(text=str(p.name), size_hint_y=None)
                grid.add_widget(btn)

    def open_output_folder(self):
        p = Path(App.get_running_app().output_dir)/"summaries"
        p.mkdir(parents=True, exist_ok=True)
        import webbrowser
        webbrowser.open(str(p))

class CodefolioApp(App):
    config_data = {}
    config_path = Path.home() / '.codefolio' / 'config.json'
    output_dir = Path.home() / 'codefolio_output'

    def build(self):
        self.load_config()
        self.title = 'Codefolio'
        return Builder.load_string(KV)

    def on_start(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self):
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
            else:
                self.config_data = {}
        except Exception as e:
            print('Could not load config:', e)
            self.config_data = {}

    def save_config(self):
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2)
            logs = self.root.get_screen('logs')
            logs.append_log('Configuration saved.')
        except Exception as e:
            print('Failed to save config:', e)

if __name__ == '__main__':
    CodefolioApp().run()
