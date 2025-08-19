import svelte from 'rollup-plugin-svelte';
import css from 'rollup-plugin-css-only';
import livereload from 'rollup-plugin-livereload';
import { nodeResolve } from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import terser from '@rollup/plugin-terser';

const production = !process.env.ROLLUP_WATCH;

export default {
    input: 'src/main.js',
    output: {
        sourcemap: true,
        format: 'iife',
        name: 'app',
        file: 'public/build/bundle.js'
    },
    plugins: [
        svelte({
            compilerOptions: { dev: !production } // ← buraya taşındı
        }),
        css({ output: 'bundle.css' }),
        nodeResolve({
            browser: true,
            exportConditions: ['svelte'], // uyarıyı da keser
            dedupe: ['svelte']
        }),
        commonjs(),
        !production && livereload('public'),
        production && terser()
    ],
    watch: { clearScreen: false }
};
