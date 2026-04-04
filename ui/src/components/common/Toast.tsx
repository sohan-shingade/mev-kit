import { useEffect, useState } from "react";
import { X } from "lucide-react";

type ToastType = "success" | "error" | "warning" | "info";

interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
}

let _setToasts: React.Dispatch<React.SetStateAction<ToastItem[]>> | null = null;
let _counter = 0;

export function toast(message: string, type: ToastType = "info") {
  if (!_setToasts) return;
  const id = ++_counter;
  _setToasts((prev) => [...prev, { id, message, type }]);
  setTimeout(() => {
    _setToasts?.((prev) => prev.filter((t) => t.id !== id));
  }, 4000);
}

function colorFor(type: ToastType) {
  switch (type) {
    case "success":
      return "border-accent-green text-accent-green";
    case "error":
      return "border-accent-red text-accent-red";
    case "warning":
      return "border-accent-amber text-accent-amber";
    default:
      return "border-accent-indigo text-accent-indigo";
  }
}

function ToastMessage({ item, onClose }: { item: ToastItem; onClose: () => void }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setVisible(true), 10);
    return () => clearTimeout(t);
  }, []);

  return (
    <div
      className={`flex items-start gap-2 bg-bg-panel border rounded px-3 py-2 shadow-lg text-sm transition-all duration-300 ${colorFor(item.type)} ${
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"
      }`}
    >
      <span className="flex-1">{item.message}</span>
      <button onClick={onClose} className="opacity-60 hover:opacity-100 mt-0.5">
        <X size={12} />
      </button>
    </div>
  );
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    _setToasts = setToasts;
    return () => {
      _setToasts = null;
    };
  }, []);

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 w-72">
      {toasts.map((item) => (
        <ToastMessage
          key={item.id}
          item={item}
          onClose={() => setToasts((prev) => prev.filter((t) => t.id !== item.id))}
        />
      ))}
    </div>
  );
}
