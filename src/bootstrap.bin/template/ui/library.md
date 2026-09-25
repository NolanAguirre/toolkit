
## Component library

The file dependency links ../../component-library. `make install` first runs
its install and build targets before installing app dependencies; `make build`
first runs its build target. The library must
export its built JavaScript entry and component-library/dist/component-library.css.
Import components from `component-library`; its stylesheet is already imported.

Vite development resolves the library to src/index.js, handles JSX in its .js
files, and watches source edits. Source components must import their own CSS;
the built stylesheet is ignored in development. Production uses the package's
built exports and stylesheet. React, ReactDOM and react-virtuoso resolve to the
app's copies in both modes. No library files are copied or created by scaffolding.
