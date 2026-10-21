import { useEffect } from 'react';
import { AccountCenterModal } from './components/AccountCenterModal';
import { AgreementModal } from './components/AgreementModal';
import { AuthModal } from './components/AuthModal';
import { CommissionDetailModal } from './components/CommissionDetailModal';
import { FeedbackModal } from './components/FeedbackModal';
import { FooterInfoBar } from './components/FooterInfoBar';
import { InviteModal } from './components/InviteModal';
import { SystemMessagesModal } from './components/SystemMessagesModal';
import { ToastContainer } from './components/ToastContainer';
import { TopBar } from './components/TopBar';
import { useAppStore } from './store/appStore';

export default function App() {
  const init = useAppStore((s) => s.init);
  const quota = useAppStore((s) => s.quota);
  const prompt = useAppStore((s) => s.prompt);
  const setPrompt = useAppStore((s) => s.setPrompt);
  const consumeAndRequestGeneration = useAppStore((s) => s.consumeAndRequestGeneration);
  const requestLoading = useAppStore((s) => s.requestLoading);
  const currentUser = useAppStore((s) => s.currentUser);
  const firstGiftVisible = useAppStore((s) => s.firstGiftVisible);
  const firstGiftReward = useAppStore((s) => s.firstGiftReward);

  useEffect(() => {
    void init();
  }, [init]);

  return (
    <div className="min-h-screen bg-ricepaper bg-[length:22px_22px,cover] font-sansCn text-ink">
      <TopBar />

      <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 pb-16 pt-8 md:px-8">
        <section className="rounded-2xl border border-daiblue/20 bg-white/55 p-6 shadow-neo backdrop-blur">
          <h1 className="font-serifCn text-3xl font-black text-daiblue md:text-4xl">象数演易 · 智能推演工作台</h1>
          <p className="mt-2 text-zheshi">宣纸纹理与回纹边框风格，结合现代交互，支持设备维度和账号维度配额管理。</p>

          <div className="mt-5 grid gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-daiblue/15 bg-white/70 p-4">
              <p className="text-sm text-zheshi">用户状态</p>
              <p className="mt-2 text-lg font-bold text-daiblue">{currentUser ? `已登录：${currentUser.username}` : '未登录设备用户'}</p>
            </div>
            <div className="rounded-xl border border-daiblue/15 bg-white/70 p-4">
              <p className="text-sm text-zheshi">赠送额度</p>
              <p className="mt-2 text-lg font-bold text-daiblue">{quota ? quota.extraBalance : '--'}</p>
            </div>
            <div className="rounded-xl border border-daiblue/15 bg-white/70 p-4">
              <p className="text-sm text-zheshi">总剩余次数</p>
              <p className="mt-2 text-lg font-bold text-cinnabar">{quota ? quota.remainingTotal : '--'}</p>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-zheshi/25 bg-[#fffef9cc] p-6 shadow-neo">
          <h2 className="font-serifCn text-2xl font-black text-daiblue">提交任务创建需求</h2>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="请输入本次生成任务需求..."
            className="mt-4 h-40 w-full rounded-xl border border-daiblue/20 bg-white/85 px-4 py-3 text-base outline-none ring-daiblue/35 transition focus:ring"
          />
          <div className="mt-4 flex items-center justify-between gap-3">
            <p className="text-sm text-zheshi">每次提交将消耗 1 次，优先扣除赠送额度，再扣除充值额度。</p>
            <button
              onClick={() => void consumeAndRequestGeneration()}
              disabled={requestLoading}
              className="rounded-full border-2 border-daiblue bg-gradient-to-b from-[#fff7ec] to-[#e7dcc5] px-6 py-2 font-serifCn text-lg font-bold text-daiblue shadow-neo transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {requestLoading ? '提交中...' : '提交需求'}
            </button>
          </div>
        </section>
      </main>

      <FooterInfoBar />

      {firstGiftVisible && firstGiftReward > 0 ? (
        <div className="fixed left-1/2 top-1/2 z-[1300] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-cinnabar/30 bg-[#fff5eb] px-8 py-5 text-center shadow-neo">
          <p className="font-serifCn text-xl font-black text-cinnabar">新用户首次登录免费赠送{firstGiftReward}次生成次数</p>
        </div>
      ) : null}

      <AuthModal />
      <InviteModal />
      <AgreementModal />
      <SystemMessagesModal />
      <FeedbackModal />
      <AccountCenterModal />
      <CommissionDetailModal />
      <ToastContainer />
    </div>
  );
}
