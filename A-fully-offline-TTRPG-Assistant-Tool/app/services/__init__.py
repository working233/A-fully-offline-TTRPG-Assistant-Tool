"""Service 容器：一次性装配所有业务服务，UI / CLI / 测试只依赖这一个对象。

分层回顾：
    UI(Web/Tk/CLI)  ->  ServiceRegistry(Services)  ->  core(IO/校验/事件)
跨层调用只允许向下，Service 之间也不要互相 new，统一在此注入，方便替身测试。
"""
from __future__ import annotations

from ..core.events import EventBus
from ..core.jsonio import cleanup_temp_files
from ..core.paths import Paths, paths as default_paths
from .backup_service import BackupService
from .campaign_service import CampaignService
from .dice_service import DiceService
from .entity_service import EntityService
from .file_manager_service import FileManagerService
from .record_service import RecordService
from .story_service import StoryService
from .trash_service import TrashService


class ServiceRegistry:
    def __init__(self, paths: Paths | None = None, bus: EventBus | None = None) -> None:
        self.paths = (paths or default_paths).ensure()
        self.bus = bus or EventBus()
        # 自愈：清掉上次被强杀留下的原子写临时文件（.tmp-*）
        self.temp_files_cleaned = cleanup_temp_files(self.paths.data)
        self.trash = TrashService(self.paths, self.bus)
        self.campaigns = CampaignService(self.paths, self.bus, trash=self.trash)
        self.files = FileManagerService(self.paths, self.bus, campaigns=self.campaigns, trash=self.trash)
        self.dice = DiceService(event_bus=self.bus, history_limit=500)
        self.entities = EntityService(self.paths, self.bus, campaigns=self.campaigns, trash=self.trash)
        self.stories = StoryService(self.paths, self.bus, campaigns=self.campaigns, trash=self.trash)
        self.records = RecordService(self.paths, self.bus, campaigns=self.campaigns)
        self.backups = BackupService(self.paths, self.bus, campaigns=self.campaigns)

    def set_persistent_dice_history(self, campaign_id: str) -> None:
        """切换跑团时，把骰子历史追加写入该跑团的 logs/dice.jsonl。"""
        try:
            campaign_dir = self.campaigns.resolve(campaign_id)
            path = campaign_dir / "logs" / "dice.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            self.dice.persist_path = str(path)
        except Exception:
            self.dice.persist_path = None
