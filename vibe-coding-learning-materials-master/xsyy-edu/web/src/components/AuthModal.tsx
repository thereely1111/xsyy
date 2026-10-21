import { FormEvent, useMemo, useState } from 'react';
import { AgreementInlineLinks } from './AgreementModal';
import { api } from '../lib/api';
import { useAppStore } from '../store/appStore';

const INVITE_HINT = '注册需填写有效邀请码（官方邀请码：XSYY2026）';

export function AuthModal() {
  const open = useAppStore((s) => s.authModalOpen);
  const closeAuthModal = useAppStore((s) => s.closeAuthModal);
  const loginSuccess = useAppStore((s) => s.loginSuccess);
  const recordAgreementAccepted = useAppStore((s) => s.recordAgreementAccepted);
  const addToast = useAppStore((s) => s.addToast);
  const deviceId = useAppStore((s) => s.deviceId);

  const [tab, setTab] = useState<'password' | 'phone'>('password');
  const [loading, setLoading] = useState(false);

  const [username, setUsername] = useState('');
  const [loginPasswordValue, setLoginPasswordValue] = useState('');

  const [regUsername, setRegUsername] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [regConfirmPassword, setRegConfirmPassword] = useState('');
  const [regInviteCode, setRegInviteCode] = useState('');

  const [phone, setPhone] = useState('');
  const [phoneCode, setPhoneCode] = useState('');
  const [phoneInviteCode, setPhoneInviteCode] = useState('');

  const [passwordLoginAgreed, setPasswordLoginAgreed] = useState(false);
  const [registerAgreed, setRegisterAgreed] = useState(false);
  const [phoneLoginAgreed, setPhoneLoginAgreed] = useState(false);

  const canRegister = useMemo(() => {
    return regUsername.trim() && regPassword.trim() && regConfirmPassword.trim() && regInviteCode.trim();
  }, [regUsername, regPassword, regConfirmPassword, regInviteCode]);

  if (!open) {
    return null;
  }

  const onPasswordLogin = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !loginPasswordValue.trim()) {
      addToast('请输入用户名和密码', 'error');
      return;
    }
    if (!passwordLoginAgreed) {
      addToast('请先同意用户协议与隐私政策', 'error');
      return;
    }
    setLoading(true);
    try {
      const result = await api.loginWithPassword({
        username: username.trim(),
        password: loginPasswordValue,
        deviceId,
      });
      loginSuccess({ token: result.token, user: result.user, quota: result.quota, inviteInfo: result.inviteInfo });
    } catch (error) {
      addToast((error as Error).message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const onRegister = async (e: FormEvent) => {
    e.preventDefault();
    if (!canRegister) {
      addToast('请填写完整注册信息', 'error');
      return;
    }
    if (!registerAgreed) {
      addToast('请先同意用户协议与隐私政策', 'error');
      return;
    }
    if (regPassword !== regConfirmPassword) {
      addToast('两次密码输入不一致', 'error');
      return;
    }

    setLoading(true);
    try {
      const inviteValidation = await api.validateInviteCode(regInviteCode.trim().toUpperCase());
      if (!inviteValidation.isValid) {
        addToast('邀请码不存在或格式不正确', 'error');
        return;
      }

      const result = await api.register({
        username: regUsername.trim(),
        password: regPassword,
        passwordConfirm: regConfirmPassword,
        inviteCode: regInviteCode.trim().toUpperCase(),
        deviceId,
      });

      loginSuccess({
        token: result.token,
        user: result.user,
        quota: result.quota,
        inviteInfo: result.inviteInfo,
        showGift: true,
        firstLoginReward: result.firstLoginReward,
      });
      recordAgreementAccepted(result.user.userId);
    } catch (error) {
      addToast((error as Error).message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const onPhoneLogin = async (e: FormEvent) => {
    e.preventDefault();
    if (!phone.trim() || !phoneCode.trim()) {
      addToast('请输入手机号和验证码', 'error');
      return;
    }
    if (!phoneLoginAgreed) {
      addToast('请先同意用户协议与隐私政策', 'error');
      return;
    }
    setLoading(true);
    try {
      const result = await api.loginWithPhone({
        phone: phone.trim(),
        code: phoneCode.trim(),
        inviteCode: phoneInviteCode.trim() || undefined,
        deviceId,
      });
      loginSuccess({
        token: result.token,
        user: result.user,
        quota: result.quota,
        inviteInfo: result.inviteInfo,
        showGift: result.firstLoginRewardGranted,
        firstLoginReward: result.firstLoginReward,
      });
    } catch (error) {
      addToast((error as Error).message, 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/55 p-4">
      <div className="w-full max-w-xl rounded-2xl border border-zheshi/30 bg-[#f8f3e8f0] p-6 shadow-neo backdrop-blur">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-serifCn text-2xl font-black text-daiblue">登入 / 注册</h2>
          <button onClick={closeAuthModal} className="rounded-full border border-daiblue/30 px-3 py-1 text-sm text-daiblue">
            关闭
          </button>
        </div>

        <div className="mb-4 flex gap-2">
          <button
            onClick={() => setTab('password')}
            className={`rounded-xl px-4 py-2 text-sm font-semibold ${tab === 'password' ? 'bg-daiblue text-white' : 'bg-white text-daiblue'}`}
          >
            账号登录 / 注册
          </button>
          <button
            onClick={() => setTab('phone')}
            className={`rounded-xl px-4 py-2 text-sm font-semibold ${tab === 'phone' ? 'bg-daiblue text-white' : 'bg-white text-daiblue'}`}
          >
            手机验证码登录
          </button>
        </div>

        {tab === 'password' ? (
          <div className="grid gap-5 md:grid-cols-2">
            <form onSubmit={onPasswordLogin} className="space-y-3 rounded-xl border border-daiblue/15 bg-white/70 p-4">
              <h3 className="font-serifCn text-lg font-bold text-daiblue">登录</h3>
              <input value={username} onChange={(e) => setUsername(e.target.value)} className="w-full rounded-lg border px-3 py-2" placeholder="用户名" />
              <input value={loginPasswordValue} onChange={(e) => setLoginPasswordValue(e.target.value)} className="w-full rounded-lg border px-3 py-2" type="password" placeholder="密码" />
              <label className="flex items-start gap-2 text-xs text-zheshi">
                <input
                  type="checkbox"
                  checked={passwordLoginAgreed}
                  onChange={(e) => setPasswordLoginAgreed(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  <AgreementInlineLinks />
                </span>
              </label>
              <button disabled={loading || !passwordLoginAgreed} className="w-full rounded-lg bg-daiblue py-2 font-semibold text-white disabled:opacity-60">登录</button>
            </form>

            <form onSubmit={onRegister} className="space-y-3 rounded-xl border border-daiblue/15 bg-white/70 p-4">
              <h3 className="font-serifCn text-lg font-bold text-daiblue">注册</h3>
              <input value={regUsername} onChange={(e) => setRegUsername(e.target.value)} className="w-full rounded-lg border px-3 py-2" placeholder="用户名（2-20位）" />
              <input value={regPassword} onChange={(e) => setRegPassword(e.target.value)} className="w-full rounded-lg border px-3 py-2" type="password" placeholder="密码（6-20位）" />
              <input value={regConfirmPassword} onChange={(e) => setRegConfirmPassword(e.target.value)} className="w-full rounded-lg border px-3 py-2" type="password" placeholder="确认密码" />
              <input value={regInviteCode} onChange={(e) => setRegInviteCode(e.target.value.toUpperCase())} className="w-full rounded-lg border px-3 py-2" placeholder="请输入邀请码" />
              <p className="text-xs text-zheshi">{INVITE_HINT}</p>
              <label className="flex items-start gap-2 text-xs text-zheshi">
                <input
                  type="checkbox"
                  checked={registerAgreed}
                  onChange={(e) => setRegisterAgreed(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  <AgreementInlineLinks />
                </span>
              </label>
              <button disabled={loading || !registerAgreed} className="w-full rounded-lg bg-cinnabar py-2 font-semibold text-white disabled:opacity-60">注册</button>
            </form>
          </div>
        ) : (
          <form onSubmit={onPhoneLogin} className="space-y-3 rounded-xl border border-daiblue/15 bg-white/70 p-4">
            <input value={phone} onChange={(e) => setPhone(e.target.value)} className="w-full rounded-lg border px-3 py-2" placeholder="手机号" />
            <input value={phoneCode} onChange={(e) => setPhoneCode(e.target.value)} className="w-full rounded-lg border px-3 py-2" placeholder="验证码" />
            <input value={phoneInviteCode} onChange={(e) => setPhoneInviteCode(e.target.value.toUpperCase())} className="w-full rounded-lg border px-3 py-2" placeholder="邀请码（新用户注册必填）" />
            <label className="flex items-start gap-2 text-xs text-zheshi">
              <input
                type="checkbox"
                checked={phoneLoginAgreed}
                onChange={(e) => setPhoneLoginAgreed(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                <AgreementInlineLinks />
              </span>
            </label>
            <button disabled={loading || !phoneLoginAgreed} className="w-full rounded-lg bg-daiblue py-2 font-semibold text-white disabled:opacity-60">登录</button>
          </form>
        )}
      </div>
    </div>
  );
}
