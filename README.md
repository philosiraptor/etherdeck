# etherdeck
plugin for Decky on steam deck that enables ethernet usb gadget mode 
<img width="1024" height="640" alt="etherdeck" src="https://github.com/user-attachments/assets/70ae4349-8c61-4703-8716-e6080a9e0153" />
PREREQUISITES:
1. you MUST have USB Dual Role Device enabled via the bios on the steam deck
2. you MUST have a compatible device that supports USB 3 connections, so far I have tested this on a Macbook Neo, a 10th gen Ipad, my own Iphone 17, you get the idea, anything that will do USB 3 speeds is basically the minimum for this to work.
3. a GOOD quality usb type c cable.
4. Decky must be installed: https://decky.xyz/


QUICK INSTALL:
1. enter the Bios on your steam deck. Press and hold the Volume Up (+) button on the top of the Deck. While holding the Volume Up button, press the Power button once. Continue holding the Volume Up button until you hear a chime or see the boot logo appear, then let go. then navigate the menus to enable USB Dual Role Device (DRD), then save the changes and reboot.
   
2. go over to the right hand side of the page and go to the Releases.
   
3. Download the zip file onto your steam deck (via desktop mode) and extract it into your plugins directory for Decky, this is usually under /home/deck/homebrew/plugins
4. profit!

USAGE:
simply plug in your target device, open the plugin by pressing the three dots button on the steam deck, navigate to the bottom of the menu to get into decky, then select USB Ethernet Gadget, and toggle the plugin on, this will then enable the usb ethernet gadget and use dhcp to assign 10.55.0.1 to the steam deck and 10.55.0.2 to the connected device.

now it is as simple as launching the steamlink client on the target device and proceeding with a normal setup for adding the steam deck as a streaming source. Enjoy! 

Q&A 

Q: why cant I just get this through decky?
A: the authors of Decky have a zero tolerance policy on any plugin that was written with AI help. maybe that'll change, but I doubt it, they are attempting to curb malicious behavior, but boy howdy thats a bad idea to rely on humans alone to do that. I wish them the best, Id love to see it included in their repo, but man, that kind of decision is a loaded burrito.

Q: did you write this?
A: a little bit. sorta. AI did alot of the lifting, I fixed DHCP and did testing.

Q: what about using X device?
A: try it and let me know! 

Q: couldnt i just use a usb kvm ?
A: probably? but then you'd have to buy another thing.

Q: whats the framerate like streaming over usb?
A: It depends! my observed latency over this link was sub millisecond most of the time, your situation is unique so your outcome is too. definitely better than trying to do this over most wifi people have.

Q: WHY?
A: why have little screen when you can have big screen.

Q: did you run out of adjectives ?
A: YES. ME TALK TOO MUCH.

Q: will you update this so it keeps working?
A: ME BUSY. ME HAVE JORB. ME NOT COMPUTER MAN. 


UNGA BUNGA CAVE MAN SOUNDS. ME ASK THINKING MACHINE TO MAKE OTHER THINKING MACHINES TALK. ME NOT CARE HOW. ME ONLY WANT RESULTS!!




