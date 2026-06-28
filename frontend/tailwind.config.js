/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: { 50: '#f0fdf4', 500: '#22c55e', 900: '#14532d' },
        danger: '#ef4444',
        warn: '#f59e0b',
      },
    },
  },
  plugins: [],
}
