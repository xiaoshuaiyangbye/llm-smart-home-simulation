import { homeGeometry } from "../data/homeGeometry";
import type { RoomId, SmartHomeState } from "../types/state";

interface HomePlan2DProps {
  state: SmartHomeState | null;
  currentRoomId: RoomId;
  onRoomSelect: (roomId: RoomId) => void;
  disabled?: boolean;
}

const labels: Record<RoomId, string> = { living_room: "客厅", bedroom: "卧室", study_room: "书房", dining_room: "餐厅", kitchen: "厨房", bathroom: "卫生间", laundry: "洗衣区", balcony: "阳台", corridor: "走廊" };
const layout = homeGeometry.map((room) => ({ ...room, label: labels[room.id],
  x: ((room.id === "corridor" ? -1.55 : Math.min(...room.polygon.map((p) => p[0]))) + 6.45) * 45 + 28,
  y: ((room.id === "corridor" ? 2.6 : Math.min(...room.polygon.map((p) => p[1]))) + 4.2) * 36 + 28,
  width: room.width * 45, height: room.depth * 36,
  points: room.polygon.map((p) => `${(p[0] + 6.45) * 45 + 28},${(p[1] + 4.2) * 36 + 28}`).join(" "),
}));

export function HomePlan2D({ state, currentRoomId, onRoomSelect, disabled = false }: HomePlan2DProps) {
  const roomsById = new Map(state?.rooms.map((room) => [room.room_id, room]));
  return (
    <div className="home-plan-2d" role="group" aria-label="可交互户型图">
      <svg viewBox="0 0 570 390" role="presentation">
        <defs>
          <linearGradient id="roomSurface" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#ffffff" />
            <stop offset="1" stopColor="#fafafa" />
          </linearGradient>
          <linearGradient id="activeRoomSurface" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#fff8f1" />
            <stop offset="1" stopColor="#fff0df" />
          </linearGradient>
          <filter id="activeRoomGlow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <rect x="8" y="8" width="554" height="374" rx="12" className="plan-shell" />
        {layout.map((planRoom) => {
          const room = roomsById.get(planRoom.id);
          const active = planRoom.id === currentRoomId;
          return (
            <g
              key={planRoom.id}
              className={`plan-room room-${planRoom.id}${active ? " active" : ""}`}
              role="button"
              aria-disabled={disabled}
              tabIndex={disabled ? -1 : 0}
              aria-label={`选择${planRoom.label}`}
              onClick={() => { if (!disabled) onRoomSelect(planRoom.id); }}
              onKeyDown={(event) => {
                if (!disabled && (event.key === "Enter" || event.key === " ")) onRoomSelect(planRoom.id);
              }}
            >
              <polygon className="room-surface" points={planRoom.points} />
              <circle className={room?.occupancy ? "room-signal occupied" : "room-signal"} cx={planRoom.x + planRoom.width - 15} cy={planRoom.y + 16} r="4" />
              <text x={planRoom.x + 12} y={planRoom.y + 25}>{planRoom.label}</text>
              {room && <text className="plan-reading" x={planRoom.x + 12} y={planRoom.y + 48}>{room.indoor_temperature_c.toFixed(1)}°C · {Math.round(room.indoor_illuminance_lux)} lx</text>}
              {active && <text className="plan-presence" x={planRoom.x + 12} y={planRoom.y + planRoom.height - 14}>我在这里</text>}
            </g>
          );
        })}
      </svg>
      <p>点击房间查看状态；当前：{layout.find((room) => room.id === currentRoomId)?.label ?? "走廊"}</p>
    </div>
  );
}
