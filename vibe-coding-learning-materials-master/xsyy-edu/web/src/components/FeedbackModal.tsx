import { ChangeEvent, FormEvent, useMemo, useState } from 'react';
import { useAppStore } from '../store/appStore';

interface PreviewImage {
  name: string;
  dataUrl: string;
}

const MAX_IMAGES = 3;
const MAX_SIZE_BYTES = 2 * 1024 * 1024;

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('图片读取失败'));
    reader.readAsDataURL(file);
  });
}

export function FeedbackModal() {
  const open = useAppStore((s) => s.feedbackModalOpen);
  const closeFeedbackModal = useAppStore((s) => s.closeFeedbackModal);
  const submitFeedback = useAppStore((s) => s.submitFeedback);
  const addToast = useAppStore((s) => s.addToast);

  const [description, setDescription] = useState('');
  const [images, setImages] = useState<PreviewImage[]>([]);
  const remaining = useMemo(() => Math.max(0, 500 - description.length), [description]);

  if (!open) {
    return null;
  }

  const onFilesChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const fileList = Array.from(event.target.files || []);
    if (!fileList.length) return;

    if (images.length + fileList.length > MAX_IMAGES) {
      addToast('最多上传 3 张图片', 'error');
      event.target.value = '';
      return;
    }

    const nextImages: PreviewImage[] = [...images];
    for (const file of fileList) {
      const isImage = ['image/jpeg', 'image/png'].includes(file.type);
      if (!isImage) {
        addToast('仅支持 JPG/PNG 图片', 'error');
        continue;
      }
      if (file.size > MAX_SIZE_BYTES) {
        addToast(`图片 ${file.name} 超过 2MB`, 'error');
        continue;
      }
      try {
        const dataUrl = await readAsDataUrl(file);
        nextImages.push({ name: file.name, dataUrl });
      } catch {
        addToast(`图片 ${file.name} 读取失败`, 'error');
      }
    }

    setImages(nextImages.slice(0, MAX_IMAGES));
    event.target.value = '';
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const value = description.trim();
    if (!value) {
      addToast('请填写问题描述', 'error');
      return;
    }
    if (value.length > 500) {
      addToast('问题描述不能超过 500 字', 'error');
      return;
    }

    submitFeedback(value, images.map((item) => item.dataUrl));
    setDescription('');
    setImages([]);
  };

  return (
    <div className="fixed inset-0 z-[1400] flex items-center justify-center bg-black/55 p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-zheshi/35 bg-[#f8f2e7f6] p-6 shadow-neo backdrop-blur">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-serifCn text-2xl font-black text-daiblue">问题反馈</h3>
          <button
            type="button"
            onClick={closeFeedbackModal}
            className="rounded-lg border border-daiblue/30 px-3 py-1.5 text-sm text-daiblue transition hover:bg-white/70"
          >
            关闭
          </button>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="mb-2 block text-sm font-semibold text-daiblue">问题描述</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="请描述您遇到的问题或建议（最多 500 字）"
              className="h-36 w-full rounded-xl border border-daiblue/20 bg-white/80 px-3 py-2 text-sm outline-none ring-daiblue/25 transition focus:ring"
              maxLength={500}
            />
            <p className="mt-1 text-right text-xs text-zheshi">剩余 {remaining} 字</p>
          </div>

          <div>
            <label className="mb-2 block text-sm font-semibold text-daiblue">上传图片（最多 3 张，JPG/PNG，2MB 内）</label>
            <input
              type="file"
              accept="image/png,image/jpeg"
              multiple
              onChange={onFilesChange}
              className="block w-full rounded-lg border border-daiblue/20 bg-white/70 p-2 text-sm"
            />

            {images.length > 0 ? (
              <div className="mt-3 grid grid-cols-3 gap-3">
                {images.map((image, index) => (
                  <div key={`${image.name}-${index}`} className="rounded-lg border border-daiblue/15 bg-white/80 p-2">
                    <img src={image.dataUrl} alt={image.name} className="h-24 w-full rounded object-cover" />
                    <button
                      type="button"
                      onClick={() => setImages((prev) => prev.filter((_, idx) => idx !== index))}
                      className="mt-2 w-full rounded-md border border-cinnabar/30 py-1 text-xs text-cinnabar transition hover:bg-cinnabar/10"
                    >
                      删除
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          <button
            type="submit"
            className="w-full rounded-lg bg-daiblue py-2.5 font-semibold text-white transition hover:brightness-95"
          >
            提交反馈
          </button>
        </form>
      </div>
    </div>
  );
}
