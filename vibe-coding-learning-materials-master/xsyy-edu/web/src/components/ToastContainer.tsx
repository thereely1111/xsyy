import { useAppStore } from '../store/appStore';

export function ToastContainer() {
  const toasts = useAppStore((s) => s.toasts);

  return (
    <div className="fixed bottom-5 right-5 z-[1200] flex w-[min(92vw,380px)] flex-col gap-3">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`rounded-xl border px-4 py-3 text-sm font-medium shadow-neo backdrop-blur ${
            toast.type === 'error'
              ? 'border-red-400/40 bg-red-900/90 text-red-100'
              : toast.type === 'success'
                ? 'border-jade/40 bg-jade/95 text-emerald-50'
                : 'border-daiblue/35 bg-daiblue/95 text-blue-50'
          }`}
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}
