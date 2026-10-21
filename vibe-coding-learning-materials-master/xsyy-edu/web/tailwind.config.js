/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        tea: '#f3efe6',
        ink: '#1f2b32',
        daiblue: '#2e4151',
        zheshi: '#8a5a44',
        jade: '#4f6d5f',
        cinnabar: '#a13f2b',
      },
      fontFamily: {
        serifCn: ['"Noto Serif SC"', 'Songti SC', 'serif'],
        sansCn: ['"Noto Sans SC"', 'PingFang SC', 'sans-serif'],
      },
      boxShadow: {
        neo: '0 8px 24px rgba(32, 42, 48, 0.18), inset 0 1px 0 rgba(255,255,255,0.35)',
      },
      backgroundImage: {
        ricepaper:
          'radial-gradient(circle at 1px 1px, rgba(110,92,73,0.08) 1px, transparent 0), linear-gradient(115deg, rgba(243,239,230,0.98) 0%, rgba(234,227,212,0.94) 100%)',
      },
    },
  },
  plugins: [],
};
