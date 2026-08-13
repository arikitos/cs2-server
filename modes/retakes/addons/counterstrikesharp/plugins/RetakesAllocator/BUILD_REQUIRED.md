# RetakesAllocator build marker

The customized allocator binary is generated from `plugins-src/retakes-allocator` by the `Build customized RetakesAllocator` workflow after source or configuration changes reach `main`.

Do not deploy Retakes while this marker exists. The workflow removes it after tests pass and the deployable plugin payload is built.
