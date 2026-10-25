// shadcn/ui Dialog pattern on Radix (focus trap, Esc, aria), restyled to the dashboard:
// white sheet, 1px rule border, 6px radius, no shadow, no animation flourish.
import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({ title, description, children, ...props }: {
  title: string; description?: string; children: ReactNode;
} & ComponentPropsWithoutRef<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/20" />
      <DialogPrimitive.Content {...props}
        className="fixed left-1/2 top-[10vh] z-50 max-h-[80vh] w-[min(640px,calc(100vw-32px))] -translate-x-1/2 overflow-y-auto rounded-md border border-rule-2 bg-sheet p-5 focus:outline-none">
        <div className="flex items-baseline justify-between gap-4 border-b border-ink pb-2">
          <DialogPrimitive.Title className="m-0 text-[15px] font-semibold">{title}</DialogPrimitive.Title>
          <DialogPrimitive.Close className="text-[13px] text-ink-2 hover:text-ink">Close</DialogPrimitive.Close>
        </div>
        {description ? (
          <DialogPrimitive.Description className="mt-2 text-[13px] text-ink-2">{description}</DialogPrimitive.Description>
        ) : (
          <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
        )}
        <div className="mt-3">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
