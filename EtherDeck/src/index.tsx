import { definePlugin, callable } from "@decky/api";
import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import { FaEthernet } from "react-icons/fa";

type State = { enabled: boolean; error?: string | null; deck_ip?: string; host_ip?: string };

const getState = callable<[], State>("get_state");
const setEnabled = callable<[boolean], State>("set_enabled");

function Content() {
  const [state, setState] = useState<State>({ enabled: false });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getState().then(setState).catch(() => {});
  }, []);

  const onChange = async (value: boolean) => {
    setBusy(true);
    try {
      setState(await setEnabled(value));
    } catch (e) {
      setState({ enabled: false, error: String(e) });
    } finally {
      setBusy(false);
    }
  };

  let description = "Present the Deck as an Ethernet adapter on the USB-C port.";
  if (state.error) description = `Failed: ${state.error}`;
  else if (state.enabled)
    description = `Deck is ${state.deck_ip}. The connected device gets ${state.host_ip} automatically.`;

  return (
    <PanelSection>
      <PanelSectionRow>
        <ToggleField
          icon={<FaEthernet />}
          label="USB Ethernet"
          description={description}
          checked={state.enabled}
          disabled={busy}
          onChange={onChange}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => ({
  name: "USB Ethernet Gadget",
  titleView: <div>USB Ethernet Gadget</div>,
  content: <Content />,
  icon: <FaEthernet />,
  onDismount() {},
}));
