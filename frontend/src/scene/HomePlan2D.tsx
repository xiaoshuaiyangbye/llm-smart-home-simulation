import type { RoomId, SmartHomeState } from "../types/state";

interface HomePlan2DProps {
  state: SmartHomeState | null;
  currentRoomId: RoomId;
  onRoomSelect: (roomId: RoomId) => void;
}

const layout: Array<{ id: RoomId; label: string; x: number; y: number; width: number; height: number }> = [
  { id: "bedroom", label: "卧室", x: 28, y: 28, width: 180, height: 112 },
  { id: "study_room", label: "书房", x: 216, y: 28, width: 166, height: 112 },
  { id: "bathroom", label: "卫生间", x: 390, y: 28, width: 116, height: 112 },
  { id: "living_room", label: "客厅", x: 28, y: 156, width: 220, height: 118 },
  { id: "dining_room", label: "餐厅", x: 256, y: 156, width: 166, height: 118 },
  { id: "kitchen", label: "厨房", x: 430, y: 156, width: 112, height: 118 },
  { id: "balcony", label: "阳台", x: 28, y: 288, width: 90, height: 72 },
  { id: "corridor", label: "走廊", x: 126, y: 288, width: 286, height: 34 },
  { id: "laundry", label: "洗衣区", x: 420, y: 288, width: 122, height: 72 },
];

export function HomePlan2D({ state, currentRoomId, onRoomSelect }: HomePlan2DProps) {
  const roomsById = new Map(state?.rooms.map((room) => [room.room_id, room]));
  return (
    <div className="home-plan-2d" role="group" aria-label="可交互户型图">
      <svg viewBox="0 0 570 390" role="img" aria-label="智能家居二维户型">
        <rect x="8" y="8" width="554" height="374" rx="12" className="plan-shell" />
        {layout.map((planRoom) => {
          const room = roomsById.get(planRoom.id);
          const active = planRoom.id === currentRoomId;
          return (
            <g
              key={planRoom.id}
              className={`plan-room${active ? " active" : ""}`}
              role="button"
              tabIndex={0}
              aria-label={`选择${planRoom.label}`}
              onClick={() => onRoomSelect(planRoom.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") onRoomSelect(planRoom.id);
              }}
            >
              <rect x={planRoom.x} y={planRoom.y} width={planRoom.width} height={planRoom.height} rx="5" />
              <text x={planRoom.x + 12} y={planRoom.y + 25}>{planRoom.label}</text>
              {room && <text className="plan-reading" x={planRoom.x + 12} y={planRoom.y + 48}>{room.indoor_temperature_c.toFixed(1)}°C · {Math.round(room.indoor_illuminance_lux)} lx</text>}
            </g>
          );
        })}
      </svg>
      <p>点击房间查看状态；当前：{layout.find((room) => room.id === currentRoomId)?.label ?? "走廊"}</p>
    </div>
  );
}
