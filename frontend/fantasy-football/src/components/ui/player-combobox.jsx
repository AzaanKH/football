"use client"

import * as React from "react"
import { Check, ChevronsUpDown } from "lucide-react"

import { cn } from "../../lib/utils"
import { Button } from "./button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "./command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "./popover"

export function PlayerCombobox({ players, value, onValueChange, placeholder = "Select player..." }) {
  const [open, setOpen] = React.useState(false)

  // Find the selected player
  const selectedPlayer = players.find(
    p => (p.player_id || p.PlayerName) === value
  )

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-full justify-between bg-slate-700/50 border-slate-600 text-white hover:bg-slate-700 hover:text-white"
        >
          {selectedPlayer ? (
            <span className="truncate">
              {selectedPlayer.PlayerName} {selectedPlayer.team ? `(${selectedPlayer.team})` : ''}
            </span>
          ) : (
            <span className="text-slate-400">{placeholder}</span>
          )}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[350px] p-0 bg-slate-800 border-slate-700" align="start">
        <Command className="bg-transparent">
          <CommandInput
            placeholder="Search players..."
            className="text-white placeholder:text-slate-400"
          />
          <CommandList className="max-h-[300px]">
            <CommandEmpty className="text-slate-400 py-6 text-center text-sm">
              No player found.
            </CommandEmpty>
            <CommandGroup>
              {players.map((player, index) => {
                const playerId = player.player_id || player.PlayerName
                const isSelected = playerId === value

                return (
                  <CommandItem
                    key={playerId || index}
                    value={`${player.PlayerName} ${player.team || ''}`}
                    onSelect={() => {
                      onValueChange(playerId === value ? "" : playerId)
                      setOpen(false)
                    }}
                    className="text-white hover:bg-slate-700 aria-selected:bg-slate-700 cursor-pointer"
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        isSelected ? "opacity-100 text-primary" : "opacity-0"
                      )}
                    />
                    <span className="flex-1 truncate">
                      {player.PlayerName}
                    </span>
                    {player.team && (
                      <span className="text-slate-400 text-xs ml-2">
                        {player.team}
                      </span>
                    )}
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
