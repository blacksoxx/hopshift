import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen } from "@testing-library/react";

vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, deviceStart: vi.fn(), devicePoll: vi.fn() } };
});

import { ApiError, api } from "@/api";
import { DeviceFlowPanel } from "./DeviceFlowDialog";
import { installDomPolyfills, renderWithProviders } from "./test-utils";

const START = {
  flow_id: "flow-1",
  user_code: "ABCD-EFGH",
  verification_uri: "https://device.sso.eu-west-1.amazonaws.com/",
  verification_uri_complete: "https://device.sso.eu-west-1.amazonaws.com/?user_code=ABCD-EFGH",
  expires_in: 600,
  interval: 2,
};

const flush = () => act(async () => {
  await vi.advanceTimersByTimeAsync(0);
});
const advance = (ms: number) => act(async () => {
  await vi.advanceTimersByTimeAsync(ms);
});

describe("DeviceFlowPanel", () => {
  beforeAll(installDomPolyfills);
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("shows the code and link, then polls at the server interval until the flow completes", async () => {
    vi.mocked(api.deviceStart).mockResolvedValue(START);
    vi.mocked(api.devicePoll)
      .mockResolvedValueOnce({ status: "pending", message: "" })
      .mockResolvedValueOnce({ status: "pending", message: "" })
      .mockResolvedValueOnce({ status: "complete", message: "signed in" });
    const onComplete = vi.fn();
    renderWithProviders(<DeviceFlowPanel connectionId="c1" onComplete={onComplete} />);

    expect(screen.getByText(/Contacting the identity provider/)).toBeInTheDocument();
    await flush();
    expect(api.deviceStart).toHaveBeenCalledWith("c1");
    expect(screen.getByTestId("device-code")).toHaveTextContent("ABCD-EFGH");
    expect(screen.getByTestId("device-url")).toHaveAttribute("href", START.verification_uri);
    expect(screen.getByTestId("device-url")).toHaveAttribute("target", "_blank");
    expect(screen.getByTestId("device-open")).toHaveAttribute("href", START.verification_uri_complete);
    expect(screen.getByTestId("device-countdown")).toHaveTextContent("10:00");
    expect(api.devicePoll).not.toHaveBeenCalled();

    await advance(2000);
    expect(api.devicePoll).toHaveBeenCalledTimes(1);
    expect(api.devicePoll).toHaveBeenCalledWith("c1", "flow-1");
    expect(screen.getByTestId("device-countdown")).toHaveTextContent("9:58");
    expect(screen.getByTestId("device-flow")).toHaveAttribute("data-phase", "pending");

    await advance(2000);
    expect(api.devicePoll).toHaveBeenCalledTimes(2);
    expect(onComplete).not.toHaveBeenCalled();

    await advance(2000);
    expect(api.devicePoll).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("device-flow")).toHaveAttribute("data-phase", "complete");
    expect(screen.getByTestId("device-complete")).toHaveTextContent("signed in");
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("device-close")).toHaveTextContent("Done");

    // Polling and the countdown stop once the flow is over.
    await advance(6000);
    expect(api.devicePoll).toHaveBeenCalledTimes(3);
  });

  it("never polls faster than every two seconds, whatever the server suggests", async () => {
    vi.mocked(api.deviceStart).mockResolvedValue({ ...START, interval: 0 });
    vi.mocked(api.devicePoll).mockResolvedValue({ status: "pending", message: "" });
    renderWithProviders(<DeviceFlowPanel connectionId="c1" />);
    await flush();
    await advance(1500);
    expect(api.devicePoll).not.toHaveBeenCalled();
    await advance(600);
    expect(api.devicePoll).toHaveBeenCalledTimes(1);
    await advance(2000);
    expect(api.devicePoll).toHaveBeenCalledTimes(2);
  });

  it("reports an expired code and offers to start again", async () => {
    vi.mocked(api.deviceStart).mockResolvedValue(START);
    vi.mocked(api.devicePoll).mockResolvedValueOnce({ status: "expired", message: "the device code expired; start again" });
    const onComplete = vi.fn();
    renderWithProviders(<DeviceFlowPanel connectionId="c1" onComplete={onComplete} />);
    await flush();
    await advance(2000);
    expect(screen.getByTestId("device-expired")).toHaveTextContent("the device code expired");
    expect(onComplete).not.toHaveBeenCalled();
    expect(screen.getByTestId("device-retry")).toHaveTextContent("Start again");

    vi.mocked(api.deviceStart).mockResolvedValue({ ...START, user_code: "WXYZ-1234" });
    fireEvent.click(screen.getByTestId("device-retry"));
    await flush();
    expect(api.deviceStart).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("device-code")).toHaveTextContent("WXYZ-1234");
  });

  it("expires locally when the countdown runs out", async () => {
    vi.mocked(api.deviceStart).mockResolvedValue({ ...START, expires_in: 5, interval: 10 });
    vi.mocked(api.devicePoll).mockResolvedValue({ status: "pending", message: "" });
    renderWithProviders(<DeviceFlowPanel connectionId="c1" />);
    await flush();
    expect(screen.getByTestId("device-countdown")).toHaveTextContent("0:05");
    await advance(5000);
    expect(screen.getByTestId("device-flow")).toHaveAttribute("data-phase", "expired");
    await advance(10000);
    expect(api.devicePoll).not.toHaveBeenCalled();
  });

  it("renders a failed start cleanly with the masked server message", async () => {
    vi.mocked(api.deviceStart).mockRejectedValue(new ApiError(400, "EndpointConnectionError: Could not connect to the endpoint URL *** (start url)"));
    renderWithProviders(<DeviceFlowPanel connectionId="c1" />);
    await flush();
    expect(screen.getByTestId("device-error")).toHaveTextContent("Could not connect to the endpoint URL ***");
    expect(screen.getByTestId("device-retry")).toHaveTextContent("Try again");
    expect(api.devicePoll).not.toHaveBeenCalled();
  });

  it("surfaces a poll error without calling onComplete", async () => {
    vi.mocked(api.deviceStart).mockResolvedValue(START);
    vi.mocked(api.devicePoll).mockResolvedValueOnce({ status: "error", message: "signed in, but verification failed: AccessDenied" });
    const onComplete = vi.fn();
    renderWithProviders(<DeviceFlowPanel connectionId="c1" onComplete={onComplete} />);
    await flush();
    await advance(2000);
    expect(screen.getByTestId("device-error")).toHaveTextContent("verification failed: AccessDenied");
    expect(onComplete).not.toHaveBeenCalled();
  });
});
