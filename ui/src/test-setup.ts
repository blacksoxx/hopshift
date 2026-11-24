import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// Every test file, with or without test-utils: findBy*/waitFor get headroom when the suite runs
// files in parallel (with coverage on CI); a passing assertion still resolves immediately.
configure({ asyncUtilTimeout: 10_000 });
