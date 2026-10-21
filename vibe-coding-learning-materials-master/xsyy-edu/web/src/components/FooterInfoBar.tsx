import { useAppStore } from '../store/appStore';

function QrCard({ src, label }: { src: string; label: string }) {
  return (
    <div className="flex flex-col items-center gap-2">
      <img
        src={src}
        alt={label}
        className="h-16 w-16 rounded-lg border border-daiblue/25 bg-white/75 object-cover sm:h-24 sm:w-24"
      />
      <p className="text-[11px] text-daiblue sm:text-sm">{label}</p>
    </div>
  );
}

export function FooterInfoBar() {
  const openAgreementModal = useAppStore((s) => s.openAgreementModal);

  return (
    <footer className="border-t border-daiblue/15 bg-[#f2eee4c9]">
      <div className="mx-auto grid w-full max-w-6xl gap-8 px-4 py-8 md:grid-cols-[1.8fr_2.2fr] md:px-8">
        <div className="grid grid-cols-2 gap-2 rounded-2xl border border-daiblue/15 bg-white/55 p-3 sm:gap-4 sm:p-4">
          <QrCard src="/images/illustrations/官方公众号.webp" label="官方公众号" />
          <QrCard src="/images/illustrations/企业微信.webp" label="象数演易交流群" />
        </div>

        <div className="rounded-2xl border border-daiblue/15 bg-white/55 p-4">
          <h4 className="font-serifCn text-lg font-black text-daiblue">平台信息</h4>
          <div className="mt-3 grid gap-2 text-sm text-ink sm:grid-cols-2">
            <p>
              协议：
              <button
                type="button"
                onClick={() => openAgreementModal('user')}
                className="ml-1 text-daiblue underline decoration-daiblue/45 underline-offset-2 transition hover:text-cinnabar"
              >
                用户协议
              </button>
              /
              <button
                type="button"
                onClick={() => openAgreementModal('privacy')}
                className="ml-1 text-daiblue underline decoration-daiblue/45 underline-offset-2 transition hover:text-cinnabar"
              >
                隐私政策
              </button>
            </p>
            <p>联系电话：40068-40020</p>
            <p>邮箱：liumingjun@tipdm.com</p>
          </div>
        </div>
      </div>
    </footer>
  );
}
