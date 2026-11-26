import jqhtml from '@jqhtml/vite-plugin';

// GitHub Pages serves the project at /ouro/.
// After attaching a custom domain, set SITE_BASE=/ and add site/public/CNAME.
const base = process.env.SITE_BASE || '/ouro/';

export default {
  base,
  appType: 'mpa',
  server: {
    host: true,
  },
  plugins: [jqhtml()],
  build: {
    rollupOptions: {
      input: ['index.html', 'docs/index.html'],
    },
  },
};
